"""Payment models: monthly fees, discounts and automatic debt calculation."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from common.models import BaseModel
from common.querysets import ActiveQuerySet, RoleScopedQuerySet
from common.utils import month_start


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Naqd")
    CARD = "card", _("Plastik karta")
    BANK_TRANSFER = "bank_transfer", _("Bank o'tkazmasi")
    CLICK = "click", _("Click")
    UZCARD = "uzcard", _("Uzcard / Humo")
    OTHER = "other", _("Boshqa")


class PaymentType(models.TextChoices):
    PAYMENT = "payment", _("To'lov")
    REFUND = "refund", _("Qaytarish")
    PARTIAL = "partial", _("Qisman to'lov")


class PaymentStatus(models.TextChoices):
    PAID = "paid", _("To'landi")
    PENDING = "pending", _("Kutilmoqda")
    CANCELLED = "cancelled", _("Bekor qilindi")
    FAILED = "failed", _("Muvaffaqiyatsiz")


class DebtStatus(models.TextChoices):
    UNPAID = "unpaid", _("To'lanmagan")
    PARTIAL = "partial", _("Qisman to'langan")
    PAID = "paid", _("To'langan")
    OVERDUE = "overdue", _("Muddati o'tgan")
    WAIVED = "waived", _("Yozildi (kechirildi)")


class DiscountType(models.TextChoices):
    PERCENT = "percent", _("Foiz")
    FIXED = "fixed", _("Qat'iy summa")


class PaymentQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "PaymentQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "PaymentQuerySet":
        return self

    def scope_branch_admin(self, user) -> "PaymentQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_manager(self, user) -> "PaymentQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_teacher(self, user) -> "PaymentQuerySet":
        return self.none()

    def scope_student(self, user) -> "PaymentQuerySet":
        return self.filter(student__user=user)

    def scope_parent(self, user) -> "PaymentQuerySet":
        return self.filter(student__parents=user).distinct()

    def with_related(self) -> "PaymentQuerySet":
        return self.select_related("branch", "student", "enrollment", "received_by")


class DebtQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "DebtQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "DebtQuerySet":
        return self

    def scope_branch_admin(self, user) -> "DebtQuerySet":
        return self.filter(student__branch_id=user.branch_id)

    def scope_manager(self, user) -> "DebtQuerySet":
        return self.filter(student__branch_id=user.branch_id)

    def scope_teacher(self, user) -> "DebtQuerySet":
        return self.none()

    def scope_student(self, user) -> "DebtQuerySet":
        return self.filter(student__user=user)

    def scope_parent(self, user) -> "DebtQuerySet":
        return self.filter(student__parents=user).distinct()

    def open_debts(self) -> "DebtQuerySet":
        return self.filter(status__in=[DebtStatus.UNPAID, DebtStatus.PARTIAL, DebtStatus.OVERDUE])

    def overdue(self) -> "DebtQuerySet":
        return self.filter(status__in=[DebtStatus.UNPAID, DebtStatus.PARTIAL], due_date__lt=timezone.localdate())


class Discount(BaseModel):
    """Reusable discount (percent or fixed amount)."""

    name = models.CharField(_("name"), max_length=120)
    code = models.CharField(_("code"), max_length=30, blank=True, db_index=True)
    discount_type = models.CharField(
        _("type"), max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    value = models.DecimalField(_("value"), max_digits=12, decimal_places=2, default=0)
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.CASCADE, null=True, blank=True,
        related_name="discounts", verbose_name=_("branch"),
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, null=True, blank=True,
        related_name="discounts", verbose_name=_("course"),
    )
    description = models.CharField(_("description"), max_length=255, blank=True)
    valid_from = models.DateField(_("valid from"), null=True, blank=True)
    valid_to = models.DateField(_("valid to"), null=True, blank=True)
    is_auto_apply = models.BooleanField(_("auto apply"), default=False)

    objects = models.Manager()
    active = ActiveQuerySet.as_manager()

    class Meta:
        db_table = "payments_discount"
        verbose_name = _("Chegirma")
        verbose_name_plural = _("Chegirmalar")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.name} ({self.value}{'%' if self.discount_type == 'percent' else ''})"

    @property
    def is_valid_today(self) -> bool:
        today = timezone.localdate()
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_to and today > self.valid_to:
            return False
        return self.is_active


class Payment(BaseModel):
    """A money transaction (monthly fee payment or refund)."""

    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="payments", verbose_name=_("branch")
    )
    student = models.ForeignKey(
        "students.Student", on_delete=models.PROTECT, related_name="payments",
        verbose_name=_("student"),
    )
    enrollment = models.ForeignKey(
        "students.Enrollment", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments", verbose_name=_("enrollment"),
    )
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(_("discount"), max_digits=12, decimal_places=2, default=0)
    method = models.CharField(
        _("method"), max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    payment_type = models.CharField(
        _("type"), max_length=10, choices=PaymentType.choices, default=PaymentType.PAYMENT
    )
    status = models.CharField(
        _("status"), max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PAID,
        db_index=True,
    )
    period_month = models.DateField(_("period"), default=month_start, db_index=True,
                                    help_text=_("Qaysi oy uchun to'lov (oy boshidagi sana)"))
    paid_at = models.DateTimeField(_("paid at"), default=timezone.now, db_index=True)
    receipt_no = models.CharField(_("receipt no"), max_length=30, blank=True, db_index=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_payments",
        verbose_name=_("cashier"),
    )
    note = models.TextField(_("note"), blank=True)

    objects = models.Manager()
    active = PaymentQuerySet.as_manager()

    class Meta:
        db_table = "payments_payment"
        verbose_name = _("To'lov")
        verbose_name_plural = _("To'lovlar")
        ordering = ("-paid_at",)
        indexes = [
            models.Index(fields=["student", "period_month"], name="idx_payment_student_period"),
            models.Index(fields=["branch", "paid_at"], name="idx_payment_branch_paid"),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.student_id} {self.amount}"

    def clean(self) -> None:
        errors: Dict[str, str] = {}
        if self.amount is not None and self.amount < 0:
            errors["amount"] = _("Summa manfiy bo'lmasligi kerak.")
        if self.payment_type == PaymentType.REFUND and self.amount is not None and self.amount <= 0:
            errors["amount"] = _("Qaytarish summasi 0 dan katta bo'lishi kerak.")
        if errors:
            raise ValidationError(errors)

    # -- computed ----------------------------------------------------------
    @property
    def total(self) -> Decimal:
        base = Decimal(self.amount or 0)
        if self.payment_type == PaymentType.REFUND:
            return -base
        return base

    @property
    def is_paid(self) -> bool:
        return self.status == PaymentStatus.PAID

    @property
    def period_label(self) -> str:
        return (self.period_month or month_start()).strftime("%Y-%m")


class Debt(BaseModel):
    """Expected money for one student + one month (auto generated)."""

    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="debts", verbose_name=_("student")
    )
    enrollment = models.ForeignKey(
        "students.Enrollment", on_delete=models.CASCADE, related_name="debts", verbose_name=_("enrollment")
    )
    period_month = models.DateField(_("period"), default=month_start, db_index=True)
    amount_due = models.DecimalField(_("amount due"), max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(_("amount paid"), max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField(_("due date"), db_index=True)
    status = models.CharField(
        _("status"), max_length=10, choices=DebtStatus.choices, default=DebtStatus.UNPAID,
        db_index=True,
    )
    note = models.CharField(_("note"), max_length=255, blank=True)

    objects = models.Manager()
    active = DebtQuerySet.as_manager()

    class Meta:
        db_table = "payments_debt"
        verbose_name = _("Qarz")
        verbose_name_plural = _("Qarzlar")
        ordering = ("-period_month",)
        constraints = [
            models.UniqueConstraint(
                fields=["student", "period_month"], name="uniq_debt_per_student_month"
            ),
        ]
        indexes = [models.Index(fields=["status", "due_date"], name="idx_debt_status_due")]

    def __str__(self) -> str:
        return f"{self.student_id} {self.period_month:%Y-%m}: {self.remaining}"

    def save(self, *args, **kwargs) -> None:
        self.refresh_status()
        super().save(*args, **kwargs)

    @property
    def remaining(self) -> Decimal:
        return max(Decimal(self.amount_due or 0) - Decimal(self.amount_paid or 0), Decimal("0"))

    @property
    def is_overdue(self) -> bool:
        return (
            self.status in (DebtStatus.UNPAID, DebtStatus.PARTIAL)
            and self.due_date < timezone.localdate()
        )

    @property
    def days_overdue(self) -> int:
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days

    def refresh_status(self) -> "Debt":
        if self.status == DebtStatus.WAIVED:
            return self
        remaining = self.remaining
        if remaining <= 0:
            self.status = DebtStatus.PAID
        elif self.amount_paid > 0:
            self.status = DebtStatus.PARTIAL
        elif self.due_date < timezone.localdate():
            self.status = DebtStatus.OVERDUE
        else:
            self.status = DebtStatus.UNPAID
        return self
