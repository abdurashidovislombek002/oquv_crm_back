"""Payment & debt business logic (the heart of the finance module)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import User
from apps.students.models import Enrollment, EnrollmentStatus, Student
from common.exceptions import BusinessRuleError, NotFoundError
from common.services import BaseService
from common.utils import add_months, month_end, month_start

from .models import Debt, DebtStatus, Discount, Payment, PaymentStatus, PaymentType


class PaymentService(BaseService):
    model = Payment

    @classmethod
    @transaction.atomic
    def create_payment(cls, data: Dict[str, Any], *, actor: Optional[User] = None) -> Payment:
        payload = cls.cleanup(data)
        student = payload.get("student")
        if isinstance(student, int):
            student = Student.objects.filter(pk=student).first()
        if student is None:
            raise BusinessRuleError(detail="O'quvchi tanlash majburiy.", code="student_required")
        if not student.is_active:
            raise BusinessRuleError(detail="O'quvchi arxivda.", code="student_inactive")

        enrollment = payload.get("enrollment")
        if isinstance(enrollment, int):
            enrollment = Enrollment.objects.filter(pk=enrollment).first()
        if enrollment is None:
            enrollment = cls._default_enrollment(student, payload.get("group"))
        if enrollment is not None and enrollment.student_id != student.pk:
            raise BusinessRuleError(
                detail="Biriktirish boshqa o'quvchiga tegishli.", code="enrollment_mismatch"
            )

        period = payload.get("period_month")
        if isinstance(period, str):
            period = parse_date(period)
        period = month_start(period or timezone.localdate())

        amount = Decimal(payload.pop("amount", 0) or 0)
        payment_type = payload.get("payment_type", PaymentType.PAYMENT)
        if amount <= 0:
            raise BusinessRuleError(detail="To'lov summasi 0 dan katta bo'lishi kerak.", code="invalid_amount")

        payment = Payment(
            **payload,
            branch=payload.get("branch") or student.branch,
            student=student,
            enrollment=enrollment,
            amount=amount,
            payment_type=payment_type,
            period_month=period,
            receipt_no=cls._generate_receipt_no(),
            received_by=actor,
        )
        payment.full_clean(exclude=["received_by"])
        payment.save()

        if payment.payment_type != PaymentType.REFUND:
            DebtService.distribute_payment(payment)
            cls._mark_enrollment_paid(enrollment, period)
        else:
            DebtService.recalculate_all_for_student(student)
        return payment

    @classmethod
    def refund(cls, payment: Payment, amount: Decimal, *, actor: Optional[User] = None,
               note: str = "") -> Payment:
        if payment.payment_type == PaymentType.REFUND:
            raise BusinessRuleError(detail="Bu allaqachon qaytarish.", code="already_refund")
        return cls.create_payment(
            {
                "student": payment.student,
                "enrollment": payment.enrollment,
                "branch": payment.branch,
                "amount": amount,
                "payment_type": PaymentType.REFUND,
                "method": payment.method,
                "period_month": payment.period_month,
                "note": note or f"{payment.receipt_no} raqamli to'lov qaytarildi",
            },
            actor=actor,
        )

    @classmethod
    def history(cls, student: Student, *, period_from: Optional[date] = None,
                period_to: Optional[date] = None) -> List[Payment]:
        queryset = Payment.active.filter(student=student)
        if period_from:
            queryset = queryset.filter(period_month__gte=month_start(period_from))
        if period_to:
            queryset = queryset.filter(period_month__lte=month_start(period_to))
        return list(queryset.order_by("-paid_at"))

    @classmethod
    def period_report(cls, *, branch_id: Optional[int] = None, year: Optional[int] = None,
                      month: Optional[int] = None) -> Dict[str, Any]:
        queryset = Payment.active.filter(status=PaymentStatus.PAID)
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        if year and month:
            queryset = queryset.filter(
                period_month__year=year, period_month__month=month
            )
        aggregates = queryset.aggregate(
            total=Sum("amount"),
            count=Count("id"),
        )
        by_method = list(
            queryset.values("method").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")
        )
        return {
            "total": aggregates["total"] or Decimal("0"),
            "count": aggregates["count"] or 0,
            "by_method": by_method,
        }

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _default_enrollment(student: Student, group: Any = None) -> Optional[Enrollment]:
        queryset = Enrollment.active.filter(
            student=student, is_active=True, status=EnrollmentStatus.ACTIVE
        )
        if group is not None:
            group_id = group.id if hasattr(group, "id") else group
            queryset = queryset.filter(group_id=group_id)
        return queryset.first()

    @staticmethod
    def _mark_enrollment_paid(enrollment: Optional[Enrollment], period: date) -> None:
        if enrollment is None:
            return
        if month_start(period) == month_start(timezone.localdate()):
            enrollment.is_paid_current_month = True
            enrollment.save(update_fields=["is_paid_current_month", "updated_at"])

    @staticmethod
    def _generate_receipt_no() -> str:
        return f"R{uuid.uuid4().hex[:10].upper()}"


class DebtService(BaseService):
    """Automatic monthly fee + debt calculation."""

    model = Debt

    #: a month must be paid until the 10th of the following month
    DUE_DAY = 10

    @classmethod
    @transaction.atomic
    def generate_for_student(cls, student: Student, *, months_back: int = 0,
                             months_forward: int = 0) -> List[Debt]:
        """Creates/updates one Debt row per month per active enrollment."""
        today = timezone.localdate()
        first_period = month_start(add_months(today, -months_back))
        last_period = month_start(add_months(today, months_forward))
        created: List[Debt] = []
        enrollments = Enrollment.active.filter(
            student=student, is_active=True, status=EnrollmentStatus.ACTIVE
        ).select_related("group")

        for enrollment in enrollments:
            period = month_start(max(enrollment.start_date, first_period))
            start_month = month_start(enrollment.start_date)
            while period <= last_period:
                if period >= start_month:
                    debt, was_created = cls._upsert(enrollment, period)
                    created.append(debt)
                period = month_start(add_months(period, 1))
        cls.refresh_overdue()
        return created

    @classmethod
    def _upsert(cls, enrollment: Enrollment, period: date) -> Any:
        amount_due = enrollment.final_fee
        debt, _created = Debt.objects.get_or_create(
            student=enrollment.student,
            period_month=period,
            defaults={
                "enrollment": enrollment,
                "amount_due": amount_due,
                "due_date": cls.due_date_for(period),
            },
        )
        if not debt.is_active:
            debt.is_active = True
        debt.enrollment = enrollment
        debt.amount_due = amount_due
        debt.due_date = cls.due_date_for(period)
        debt.save()
        return debt

    @classmethod
    def generate_for_branch(cls, branch_id: Optional[int] = None, *, months_forward: int = 0) -> int:
        queryset = Student.active.filter(is_active=True, status="active")
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        count = 0
        for student in queryset:
            cls.generate_for_student(student, months_forward=months_forward)
            count += 1
        return count

    @classmethod
    @transaction.atomic
    def distribute_payment(cls, payment: Payment) -> List[Debt]:
        """FIFO: a payment covers the oldest unpaid periods first."""
        remaining = Decimal(payment.amount or 0)
        debts = list(
            Debt.objects.filter(
                student=payment.student, is_active=True
            ).exclude(status__in=[DebtStatus.PAID, DebtStatus.WAIVED])
            .order_by("period_month")
        )
        touched: List[Debt] = []
        for debt in debts:
            if remaining <= 0:
                break
            outstanding = debt.remaining
            if outstanding <= 0:
                continue
            applied = min(outstanding, remaining)
            debt.amount_paid = Decimal(debt.amount_paid or 0) + applied
            remaining -= applied
            debt.save()
            touched.append(debt)
        return touched

    @classmethod
    def recalculate_all_for_student(cls, student: Student) -> List[Debt]:
        debts = list(
            Debt.objects.filter(student=student, is_active=True)
            .order_by("period_month")
        )
        paid_total = Decimal("0")
        refunds = Decimal("0")
        for payment in Payment.objects.filter(student=student, is_active=True,
                                              status=PaymentStatus.PAID):
            if payment.payment_type == PaymentType.REFUND:
                refunds += Decimal(payment.amount or 0)
            else:
                paid_total += Decimal(payment.amount or 0)
        available = paid_total - refunds

        for debt in debts:
            due = Decimal(debt.amount_due or 0)
            debt.amount_paid = max(min(available, due), Decimal("0"))
            available -= debt.amount_paid
            debt.save()
        return debts

    @classmethod
    def refresh_overdue(cls, *, branch_id: Optional[int] = None) -> int:
        queryset = Debt.objects.filter(
            is_active=True, status__in=[DebtStatus.UNPAID, DebtStatus.PARTIAL],
            due_date__lt=timezone.localdate(),
        )
        if branch_id:
            queryset = queryset.filter(student__branch_id=branch_id)
        return queryset.update(status=DebtStatus.OVERDUE)

    @classmethod
    def waive(cls, debt: Debt, *, note: str = "") -> Debt:
        debt.status = DebtStatus.WAIVED
        if note:
            debt.note = note
        debt.save(update_fields=["status", "note", "updated_at"])
        return debt

    @classmethod
    def student_summary(cls, student: Student) -> Dict[str, Any]:
        """Full balance sheet of a student: paid, expected, debts, days late."""
        debts = list(
            Debt.objects.filter(student=student, is_active=True).order_by("period_month")
        )
        paid_total = Decimal("0")
        for payment in Payment.objects.filter(
            student=student, is_active=True, status=PaymentStatus.PAID
        ):
            paid_total += Decimal(payment.total or 0)
        expected = sum((Decimal(debt.amount_due or 0) for debt in debts), Decimal("0"))
        open_debts = [debt for debt in debts if debt.status in
                      (DebtStatus.UNPAID, DebtStatus.PARTIAL, DebtStatus.OVERDUE)]
        total_debt = sum((debt.remaining for debt in open_debts), Decimal("0"))
        overdue_debts = [debt for debt in open_debts if debt.is_overdue]
        days_overdue = max((debt.days_overdue for debt in overdue_debts), default=0)
        return {
            "student_id": student.pk,
            "student": student.full_name,
            "branch": student.branch.name if student.branch_id else None,
            "total_paid": paid_total,
            "total_expected": expected,
            "total_debt": total_debt,
            "has_debt": bool(total_debt > 0),
            "overdue_debts_count": len(overdue_debts),
            "days_overdue": days_overdue,
            "months_unpaid": len(open_debts),
            "last_payment_at": (
                Payment.objects.filter(student=student, is_active=True)
                .order_by("-paid_at")
                .values_list("paid_at", flat=True)
                .first()
            ),
            "debts": [
                {
                    "id": debt.pk,
                    "period": debt.period_month.strftime("%Y-%m"),
                    "amount_due": debt.amount_due,
                    "amount_paid": debt.amount_paid,
                    "remaining": debt.remaining,
                    "status": debt.status,
                    "due_date": debt.due_date,
                    "days_overdue": debt.days_overdue,
                }
                for debt in debts
            ],
        }

    @classmethod
    def current_period_due_date(cls, period: Optional[date] = None) -> date:
        return cls.due_date_for(period or timezone.localdate())

    @classmethod
    def due_date_for(cls, period: date) -> date:
        period = month_start(period)
        next_month = month_start(add_months(period, 1))
        return date(next_month.year, next_month.month, cls.DUE_DAY)

    @classmethod
    def debtors(cls, *, branch_id: Optional[int] = None, min_amount: Optional[Decimal] = None
                ) -> List[Dict[str, Any]]:
        queryset = (
            Debt.objects.open_debts()
            .values("student_id", "student__first_name", "student__last_name",
                    "student__branch_id", "student__branch__name", "student__phone")
            .annotate(total=Sum("amount_due") - Sum("amount_paid"))
            .order_by("-total")
        )
        if branch_id:
            queryset = queryset.filter(student__branch_id=branch_id)
        if min_amount:
            queryset = queryset.filter(total__gte=min_amount)
        return [
            {
                "student_id": row["student_id"],
                "student": f"{row['student__first_name']} {row['student__last_name']}".strip(),
                "phone": row["student__phone"],
                "branch": row["student__branch__name"],
                "debt": row["total"],
            }
            for row in queryset
        ]


class DiscountService(BaseService):
    model = Discount

    @classmethod
    def create_discount(cls, data: Dict[str, Any]) -> Discount:
        payload = cls.cleanup(data)
        if payload.get("discount_type") == "percent" and Decimal(payload.get("value", 0)) > 100:
            raise BusinessRuleError(
                detail="Foiz chegirma 100 dan katta bo'lmasligi kerak.", code="invalid_discount"
            )
        return Discount.objects.create(**payload)

    @classmethod
    def auto_applicable(cls, branch: Any = None, course: Any = None) -> Optional[Discount]:
        return (
            Discount.active.filter(is_active=True, is_auto_apply=True)
            .filter(Q(branch__isnull=True) | Q(branch=branch))
            .filter(Q(course__isnull=True) | Q(course=course))
            .order_by("-created_at")
            .first()
        )
