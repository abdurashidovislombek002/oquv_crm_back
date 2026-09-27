"""Dashboard aggregations.

All analytics live here (no models): the services query the other apps and
return plain dictionaries, the viewset only renders them.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from common.constants import month_start
from common.services import BaseService
from common.utils import add_months, month_end


class AnalyticsService(BaseService):
    """Base helper: resolves the branch scope for the current user."""

    @staticmethod
    def resolve_branch(user, requested_branch_id: Optional[Any] = None) -> Optional[int]:
        if getattr(user, "is_superuser", False) or getattr(user, "role", None) == "super_admin":
            return int(requested_branch_id) if requested_branch_id else None
        return getattr(user, "branch_id", None)

    @staticmethod
    def date_range(params) -> tuple[date, date]:
        today = timezone.localdate()
        start = params.get("date_from") or params.get("from")
        end = params.get("date_to") or params.get("to")
        start_date = parse_date(start) if start else month_start(add_months(today, -5))
        end_date = parse_date(end) if end else today
        return start_date, end_date


class DashboardService(AnalyticsService):
    """``/api/v1/dashboard/summary/``"""

    @classmethod
    def summary(cls, user, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from apps.attendance.models import AttendanceRecord, AttendanceStatus, Lesson
        from apps.crm_leads.models import Lead, LeadStatus
        from apps.groups.models import Group, GroupStatus
        from apps.payments.models import Debt, DebtStatus, Payment, PaymentStatus
        from apps.students.models import Enrollment, EnrollmentStatus, Student, StudentStatus

        params = params or {}
        branch_id = cls.resolve_branch(user, params.get("branch_id"))
        start_date, end_date = cls.date_range(params)
        today = timezone.localdate()
        month = month_start(today)

        def scoped(queryset, field="branch_id"):
            return queryset.filter(**{field: branch_id}) if branch_id else queryset

        # -- CRM ---------------------------------------------------------
        leads = scoped(Lead.active.filter(is_active=True))
        leads_created = leads.filter(created_at__date__range=(start_date, end_date))
        converted = leads.filter(status=LeadStatus.CONVERTED)

        # -- students ----------------------------------------------------
        students = scoped(Student.active.filter(is_active=True))
        active_students = students.filter(status=StudentStatus.ACTIVE)
        new_students = students.filter(created_at__date__range=(start_date, end_date))

        # -- groups ------------------------------------------------------
        groups = scoped(Group.active.filter(is_active=True))
        groups_with_counts = groups.annotate(
            students_total=Count(
                "enrollments",
                filter=Q(enrollments__is_active=True, enrollments__status=EnrollmentStatus.ACTIVE),
                distinct=True,
            )
        )
        capacity = groups_with_counts.aggregate(total=Sum("capacity"))["total"] or 0
        filled = groups_with_counts.aggregate(total=Sum("students_total"))["total"] or 0

        # -- money -------------------------------------------------------
        payments = scoped(
            Payment.active.filter(is_active=True, status=PaymentStatus.PAID,
                                  payment_type="payment")
        )
        period_payments = payments.filter(
            period_month__date__range=(start_date, month_end(start_date))
        ) if start_date > month_start(add_months(month_end(start_date), -1)) else payments
        income_month = payments.filter(period_month=month)
        income_range = payments.filter(period_month__gte=month_start(start_date),
                                       period_month__lte=end_date)
        debts = Debt.active.filter(
            student__branch_id=branch_id
        ).open_debts() if branch_id else Debt.active.open_debts()

        # -- attendance --------------------------------------------------
        attendance_range = AttendanceRecord.active.filter(
            lesson__date__range=(start_date, end_date)
        )
        if branch_id:
            attendance_range = attendance_range.filter(lesson__branch_id=branch_id)
        total_records = attendance_range.count()
        present_records = attendance_range.filter(
            status__in=[AttendanceStatus.PRESENT, AttendanceStatus.ONLINE]
        ).count()

        return {
            "generated_at": timezone.now(),
            "period": {"from": start_date, "to": end_date},
            "branch_id": branch_id,
            "crm": {
                "leads_total": leads.count(),
                "leads_new_in_period": leads_created.count(),
                "leads_converted": converted.count(),
                "leads_rejected": leads.filter(status=LeadStatus.REJECTED).count(),
                "conversion_rate": cls._conversion_rate(leads),
                "by_status": list(
                    leads.values("status").annotate(count=Count("id")).order_by("status")
                ),
                "by_source": list(
                    leads.values("source").annotate(count=Count("id")).order_by("-count")[:10]
                ),
            },
            "students": {
                "total": students.count(),
                "active": active_students.count(),
                "frozen": students.filter(status=StudentStatus.FROZEN).count(),
                "graduated": students.filter(status=StudentStatus.GRADUATED).count(),
                "new_in_period": new_students.count(),
                "without_group": students.filter(
                    enrollments__isnull=True
                ).count(),
            },
            "groups": {
                "total": groups.count(),
                "active": groups.filter(status=GroupStatus.ACTIVE).count(),
                "planned": groups.filter(status=GroupStatus.PLANNED).count(),
                "capacity_total": capacity,
                "students_enrolled": filled,
                "fill_rate": round(filled / capacity * 100, 2) if capacity else 0.0,
                "free_seats": max(capacity - filled, 0),
            },
            "finance": {
                "income_this_month": income_month.aggregate(total=Sum("amount"))["total"] or Decimal("0"),
                "income_in_period": income_range.aggregate(total=Sum("amount"))["total"] or Decimal("0"),
                "payments_count": income_month.count(),
                "total_debt": debts.aggregate(
                    total=Sum("amount_due") - Sum("amount_paid")
                )["total"] or Decimal("0"),
                "debtors_count": debts.values("student_id").distinct().count(),
                "overdue_count": debts.filter(status=DebtStatus.OVERDUE).count(),
            },
            "attendance": {
                "records": total_records,
                "present": present_records,
                "absent": attendance_range.filter(status=AttendanceStatus.ABSENT).count(),
                "late": attendance_range.filter(status=AttendanceStatus.LATE).count(),
                "rate": round(present_records / total_records * 100, 2) if total_records else 0.0,
                "lessons_this_month": scoped(
                    Lesson.active.filter(date__range=(month, month_end(month)))
                ).count(),
            },
            "notifications": cls._notification_stats(branch_id),
        }

    @staticmethod
    def _conversion_rate(leads) -> float:
        total = leads.count()
        if not total:
            return 0.0
        return round(leads.filter(status="converted").count() / total * 100, 2)

    @staticmethod
    def _notification_stats(branch_id: Optional[int]) -> Dict[str, Any]:
        from apps.notifications.models import Notification

        queryset = Notification.active.filter(is_active=True)
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        return {
            "total": queryset.count(),
            "pending": queryset.filter(status__in=["pending", "queued"]).count(),
            "sent": queryset.filter(status="sent").count(),
            "failed": queryset.filter(status="failed").count(),
        }


class LeadAnalyticsService(AnalyticsService):
    """``/api/v1/dashboard/leads/``"""

    @classmethod
    def report(cls, user, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from apps.crm_leads.models import Lead, LeadSource, LeadStatus

        params = params or {}
        branch_id = cls.resolve_branch(user, params.get("branch_id"))
        queryset = Lead.active.filter(is_active=True)
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        by_source = list(
            queryset.values("source").annotate(count=Count("id")).order_by("-count")
        )
        conversion_by_source = []
        for row in by_source:
            source_qs = queryset.filter(source=row["source"])
            converted = source_qs.filter(status=LeadStatus.CONVERTED).count()
            conversion_by_source.append(
                {
                    "source": row["source"],
                    "label": dict(LeadSource.choices).get(row["source"], row["source"]),
                    "count": row["count"],
                    "converted": converted,
                    "conversion_rate": round(converted / row["count"] * 100, 2)
                    if row["count"] else 0.0,
                }
            )

        monthly = cls._monthly_series(
            queryset, date_field="created_at", status_field="status",
            extra=(
                queryset.filter(status=LeadStatus.CONVERTED)
                .annotate(month=F("converted_at"))
            ),
        )
        return {
            "total": queryset.count(),
            "by_status": list(queryset.values("status").annotate(count=Count("id"))),
            "by_source": by_source,
            "conversion_by_source": conversion_by_source,
            "monthly_created": cls._created_per_month(queryset),
            "monthly_converted": cls._converted_per_month(queryset),
            "average_days_to_convert": cls._average_days_to_convert(queryset),
            "lost_reasons": list(
                queryset.filter(status=LeadStatus.REJECTED)
                .exclude(rejected_reason="")
                .values("rejected_reason")
                .annotate(count=Count("id"))
                .order_by("-count")[:10]
            ),
        }

    @staticmethod
    def _created_per_month(queryset) -> List[Dict[str, Any]]:
        from django.db.models.functions import TruncMonth

        rows = (
            queryset.annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
        return [{"month": row["month"].strftime("%Y-%m"), "count": row["count"]} for row in rows]

    @staticmethod
    def _converted_per_month(queryset) -> List[Dict[str, Any]]:
        from django.db.models.functions import TruncMonth

        rows = (
            queryset.filter(status=LeadStatus.CONVERTED)
            .annotate(month=TruncMonth("converted_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
        return [{"month": row["month"].strftime("%Y-%m"), "count": row["count"]} for row in rows]

    @staticmethod
    def _average_days_to_convert(queryset) -> float:
        converted = list(
            queryset.filter(status=LeadStatus.CONVERTED).exclude(converted_at=None)
            .values("created_at", "converted_at")
        )
        if not converted:
            return 0.0
        total = sum((row["converted_at"] - row["created_at"]).days for row in converted)
        return round(total / len(converted), 2)

    @staticmethod
    def _monthly_series(queryset, **kwargs) -> List[Dict[str, Any]]:  # pragma: no cover
        return []


class PaymentAnalyticsService(AnalyticsService):
    """``/api/v1/dashboard/payments/``"""

    @classmethod
    def report(cls, user, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from django.db.models.functions import TruncMonth

        from apps.payments.models import Debt, DebtStatus, Payment, PaymentStatus

        params = params or {}
        branch_id = cls.resolve_branch(user, params.get("branch_id"))
        start_date, end_date = cls.date_range(params)

        payments = Payment.active.filter(
            is_active=True, status=PaymentStatus.PAID, payment_type="payment",
            period_month__gte=month_start(start_date), period_month__lte=end_date,
        )
        debts = Debt.active.filter(
            is_active=True, status__in=[DebtStatus.UNPAID, DebtStatus.PARTIAL, DebtStatus.OVERDUE]
        )
        if branch_id:
            payments = payments.filter(branch_id=branch_id)
            debts = debts.filter(student__branch_id=branch_id)

        monthly = (
            payments.annotate(month=TruncMonth("period_month"))
            .values("month")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("month")
        )
        return {
            "period": {"from": start_date, "to": end_date},
            "collected": payments.aggregate(total=Sum("amount"))["total"] or Decimal("0"),
            "payments_count": payments.count(),
            "expected": debts.aggregate(total=Sum("amount_due"))["total"] or Decimal("0"),
            "paid_of_debts": debts.aggregate(total=Sum("amount_paid"))["total"] or Decimal("0"),
            "outstanding": debts.aggregate(
                total=Sum("amount_due") - Sum("amount_paid")
            )["total"] or Decimal("0"),
            "by_method": list(
                payments.values("method").annotate(total=Sum("amount"), count=Count("id"))
            ),
            "monthly": [
                {"month": row["month"].strftime("%Y-%m"), "total": row["total"], "count": row["count"]}
                for row in monthly
            ],
            "top_debtors": cls._top_debtors(debts),
        }

    @staticmethod
    def _top_debtors(debts, limit: int = 10) -> List[Dict[str, Any]]:
        rows = (
            debts.values("student_id", "student__first_name", "student__last_name",
                         "student__phone")
            .annotate(debt=Sum("amount_due") - Sum("amount_paid"))
            .order_by("-debt")[:limit]
        )
        return [
            {
                "student_id": row["student_id"],
                "student": f"{row['student__first_name']} {row['student__last_name']}".strip(),
                "phone": row["student__phone"],
                "debt": row["debt"],
            }
            for row in rows
        ]


class GroupAnalyticsService(AnalyticsService):
    """``/api/v1/dashboard/groups/``"""

    @classmethod
    def report(cls, user, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from apps.groups.models import Group, GroupStatus
        from apps.students.models import EnrollmentStatus

        params = params or {}
        branch_id = cls.resolve_branch(user, params.get("branch_id"))
        queryset = Group.active.filter(is_active=True).with_counts()
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        rows = list(queryset.select_related("branch", "course", "level"))
        capacity = sum(row.capacity for row in rows)
        enrolled = sum(getattr(row, "students_count", 0) for row in rows)
        return {
            "total": len(rows),
            "by_status": list(
                queryset.values("status").annotate(count=Count("id")).order_by("status")
            ),
            "capacity_total": capacity,
            "students_enrolled": enrolled,
            "free_seats": max(capacity - enrolled, 0),
            "fill_rate": round(enrolled / capacity * 100, 2) if capacity else 0.0,
            "groups": [
                {
                    "id": row.id,
                    "name": row.name,
                    "branch": row.branch.name,
                    "course": row.course.name,
                    "level": row.level.name,
                    "status": row.status,
                    "capacity": row.capacity,
                    "students": getattr(row, "students_count", 0),
                    "free_seats": max(row.capacity - getattr(row, "students_count", 0), 0),
                    "fill_rate": round(
                        getattr(row, "students_count", 0) / row.capacity * 100, 2
                    ) if row.capacity else 0.0,
                }
                for row in rows
            ],
        }


class TeacherLoadService(AnalyticsService):
    """``/api/v1/dashboard/teachers/`` — teacher workload."""

    @classmethod
    def report(cls, user, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from datetime import time as dtime

        from apps.accounts.constants import Role
        from apps.accounts.models import User
        from apps.attendance.models import Lesson
        from apps.groups.models import Group

        params = params or {}
        branch_id = cls.resolve_branch(user, params.get("branch_id"))
        start_date, end_date = cls.date_range(params)

        teachers = User.objects.filter(role=Role.TEACHER, is_active=True)
        if branch_id:
            teachers = teachers.filter(branch_id=branch_id)

        result = []
        for teacher in teachers:
            groups = Group.active.filter(
                Q(teachers=teacher) | Q(head_teacher=teacher), is_active=True
            ).distinct()
            if branch_id:
                groups = groups.filter(branch_id=branch_id)
            student_count = sum(
                getattr(group, "students_count", 0) for group in groups
            )
            lessons = Lesson.active.filter(
                Q(teacher=teacher) | Q(group__teachers=teacher),
                date__range=(start_date, end_date),
            ).distinct()
            if branch_id:
                lessons = lessons.filter(branch_id=branch_id)
            minutes = sum(lesson.duration_minutes for lesson in lessons)
            result.append(
                {
                    "teacher_id": teacher.pk,
                    "teacher": teacher.full_name,
                    "branch": teacher.branch.name if teacher.branch_id else None,
                    "groups_count": groups.count(),
                    "students_count": student_count,
                    "lessons_in_period": lessons.count(),
                    "hours_in_period": round(minutes / 60, 2),
                    "avg_students_per_group": round(student_count / groups.count(), 2)
                    if groups.count() else 0.0,
                }
            )
        result.sort(key=lambda item: item["hours_in_period"], reverse=True)
        return {
            "period": {"from": start_date, "to": end_date},
            "teachers_count": len(result),
            "total_hours": round(sum(item["hours_in_period"] for item in result), 2),
            "teachers": result,
        }


class AttendanceAnalyticsService(AnalyticsService):
    """``/api/v1/dashboard/attendance/``"""

    @classmethod
    def report(cls, user, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from apps.attendance.models import AttendanceRecord, AttendanceStatus, Lesson

        params = params or {}
        branch_id = cls.resolve_branch(user, params.get("branch_id"))
        start_date, end_date = cls.date_range(params)

        records = AttendanceRecord.active.filter(lesson__date__range=(start_date, end_date))
        lessons = Lesson.active.filter(date__range=(start_date, end_date))
        if branch_id:
            records = records.filter(lesson__branch_id=branch_id)
            lessons = lessons.filter(branch_id=branch_id)

        total = records.count()
        present = records.filter(
            status__in=[AttendanceStatus.PRESENT, AttendanceStatus.ONLINE]
        ).count()
        return {
            "period": {"from": start_date, "to": end_date},
            "lessons": lessons.count(),
            "records": total,
            "present": present,
            "absent": records.filter(status=AttendanceStatus.ABSENT).count(),
            "late": records.filter(status=AttendanceStatus.LATE).count(),
            "excused": records.filter(status=AttendanceStatus.EXCUSED).count(),
            "attendance_rate": round(present / total * 100, 2) if total else 0.0,
            "by_status": list(records.values("status").annotate(count=Count("id"))),
        }


class StudentAnalyticsService(AnalyticsService):
    """``/api/v1/dashboard/students/``"""

    @classmethod
    def report(cls, user, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from apps.students.models import Student, StudentStatus

        params = params or {}
        branch_id = cls.resolve_branch(user, params.get("branch_id"))
        queryset = Student.active.filter(is_active=True)
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        return {
            "total": queryset.count(),
            "by_status": list(queryset.values("status").annotate(count=Count("id"))),
            "by_branch": list(
                queryset.values("branch_id", "branch__name").annotate(count=Count("id"))
            ),
            "new_in_period": queryset.filter(
                created_at__date__range=cls.date_range(params)
            ).count(),
        }
