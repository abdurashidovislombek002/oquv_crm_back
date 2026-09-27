"""Student + Enrollment models."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from common.constants import format_phone
from common.models import BaseModel
from common.querysets import RoleScopedQuerySet


class StudentStatus(models.TextChoices):
    ACTIVE = "active", _("Faol")
    FROZEN = "frozen", _("Muzlatilgan")
    GRADUATED = "graduated", _("Tugatgan")
    EXPELLED = "expelled", _("Chiqarilgan")
    TRIAL = "trial", _("Sinov davrida")


class EnrollmentStatus(models.TextChoices):
    ACTIVE = "active", _("Faol")
    PAUSED = "paused", _("To'xtatilgan")
    COMPLETED = "completed", _("Tugatgan")
    LEFT = "left", _("Ketgan")
    MOVED = "moved", _("Boshqa guruhga ko'chirilgan")


class StudentQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "StudentQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "StudentQuerySet":
        return self

    def scope_branch_admin(self, user) -> "StudentQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_manager(self, user) -> "StudentQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_teacher(self, user) -> "StudentQuerySet":
        return self.filter(
            enrollments__group__in=Group_refs(user)
        ).distinct()

    def scope_student(self, user) -> "StudentQuerySet":
        return self.filter(Q(user=user) | Q(pk=self._student_pk(user)))

    def scope_parent(self, user) -> "StudentQuerySet":
        return self.filter(parents=user).distinct()

    @staticmethod
    def _student_pk(user):
        pk = getattr(user, "student_profile", None)
        return pk.pk if pk else -1

    def with_related(self) -> "StudentQuerySet":
        return self.select_related("branch", "user").prefetch_related("parents", "enrollments")

    def with_counts(self) -> "StudentQuerySet":
        return self.annotate(
            groups_count=Count(
                "enrollments",
                filter=Q(enrollments__is_active=True, enrollments__status="active"),
                distinct=True,
            )
        )


def Group_refs(user):  # pragma: no cover - tiny helper kept for clarity
    from apps.groups.models import Group

    return Group.objects.filter(Q(teachers=user) | Q(head_teacher=user)).values_list("id", flat=True)


class Student(BaseModel):
    """A learner. Optionally linked to a portal ``User`` (role=student)."""

    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="student_profile", limit_choices_to={"role": "student"},
        verbose_name=_("portal account"),
    )
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="students", verbose_name=_("branch")
    )
    first_name = models.CharField(_("first name"), max_length=120)
    last_name = models.CharField(_("last name"), max_length=120)
    middle_name = models.CharField(_("middle name"), max_length=120, blank=True)
    birth_date = models.DateField(_("birth date"), null=True, blank=True)
    gender = models.CharField(_("gender"), max_length=10, blank=True)
    phone = models.CharField(_("phone"), max_length=32, blank=True, db_index=True)
    email = models.EmailField(_("email"), blank=True)
    telegram_id = models.CharField(_("telegram id"), max_length=64, blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    school = models.CharField(_("school"), max_length=150, blank=True)
    photo_url = models.URLField(_("photo url"), blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=StudentStatus.choices, default=StudentStatus.ACTIVE,
        db_index=True,
    )
    parents = models.ManyToManyField(
        User, related_name="children", blank=True, limit_choices_to={"role": "parent"},
        verbose_name=_("parents"),
    )
    start_date = models.DateField(_("start date"), default=timezone.localdate)
    finish_date = models.DateField(_("finish date"), null=True, blank=True)
    discount_percent = models.DecimalField(
        _("personal discount %"), max_digits=5, decimal_places=2, default=0
    )
    source = models.CharField(_("source"), max_length=50, blank=True, db_index=True)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_students",
        verbose_name=_("created by"),
    )

    objects = models.Manager()
    active = StudentQuerySet.as_manager()

    class Meta:
        db_table = "students_student"
        verbose_name = _("O'quvchi")
        verbose_name_plural = _("O'quvchilar")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["branch", "status"], name="idx_student_branch_status"),
            models.Index(fields=["last_name", "first_name"], name="idx_student_name"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone or 'telefonsiz'})"

    def save(self, *args, **kwargs) -> None:
        if self.phone:
            self.phone = format_phone(self.phone)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        errors: Dict[str, str] = {}
        if self.birth_date and self.birth_date > timezone.localdate():
            errors["birth_date"] = _("Tug'ilgan sana kelajakda bo'lmasligi kerak.")
        if self.start_date and self.finish_date and self.start_date > self.finish_date:
            errors["finish_date"] = _("Tugash sanasi boshlanishdan oldin bo'lmasligi kerak.")
        if errors:
            raise ValidationError(errors)

    # -- computed ----------------------------------------------------------
    @property
    def full_name(self) -> str:
        return " ".join(
            part for part in (self.first_name, self.last_name, self.middle_name) if part
        ).strip()

    @property
    def age(self) -> int:
        if not self.birth_date:
            return 0
        today = timezone.localdate()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def active_enrollments(self) -> List["Enrollment"]:
        return list(self.enrollments.filter(is_active=True, status=EnrollmentStatus.ACTIVE))

    @property
    def groups_count(self) -> int:
        cached = getattr(self, "groups_count", None)
        if cached is not None:
            return cached
        return len(self.active_enrollments)

    @property
    def primary_group(self):
        enrollments = self.active_enrollments
        return enrollments[0].group if enrollments else None

    @property
    def is_active_student(self) -> bool:
        return self.status == StudentStatus.ACTIVE


class EnrollmentQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "EnrollmentQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "EnrollmentQuerySet":
        return self

    def scope_branch_admin(self, user) -> "EnrollmentQuerySet":
        return self.filter(group__branch_id=user.branch_id)

    def scope_manager(self, user) -> "EnrollmentQuerySet":
        return self.filter(group__branch_id=user.branch_id)

    def scope_teacher(self, user) -> "EnrollmentQuerySet":
        return self.filter(group__in=Group_refs(user)).distinct()

    def scope_student(self, user) -> "EnrollmentQuerySet":
        return self.filter(student__user=user)

    def scope_parent(self, user) -> "EnrollmentQuerySet":
        return self.filter(student__parents=user).distinct()

    def active_only(self) -> "EnrollmentQuerySet":
        return self.filter(is_active=True, status=EnrollmentStatus.ACTIVE)

    def with_related(self) -> "EnrollmentQuerySet":
        return self.select_related("student", "group", "group__course", "group__level", "created_by")


class Enrollment(BaseModel):
    """Binding of a student to a group (with fee + discount)."""

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="enrollments", verbose_name=_("student")
    )
    group = models.ForeignKey(
        "groups.Group", on_delete=models.PROTECT, related_name="enrollments", verbose_name=_("group")
    )
    status = models.CharField(
        _("status"), max_length=20, choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ACTIVE, db_index=True,
    )
    start_date = models.DateField(_("start date"), default=timezone.localdate)
    end_date = models.DateField(_("end date"), null=True, blank=True)
    monthly_fee = models.DecimalField(
        _("monthly fee"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    discount_percent = models.DecimalField(
        _("discount %"), max_digits=5, decimal_places=2, default=0
    )
    discount = models.ForeignKey(
        "payments.Discount", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="enrollments", verbose_name=_("discount"),
    )
    is_paid_current_month = models.BooleanField(_("current month paid"), default=False)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_enrollments",
        verbose_name=_("created by"),
    )

    objects = models.Manager()
    active = EnrollmentQuerySet.as_manager()

    class Meta:
        db_table = "students_enrollment"
        verbose_name = _("Guruhga biriktirish")
        verbose_name_plural = _("Guruhga biriktirishlar")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["student", "group"],
                condition=Q(is_active=True),
                name="uniq_active_enrollment_per_group",
            ),
        ]
        indexes = [models.Index(fields=["group", "status"], name="idx_enroll_group_status")]

    def __str__(self) -> str:
        return f"{self.student.full_name} -> {self.group.name}"

    def clean(self) -> None:
        errors: Dict[str, str] = {}
        if self.student_id and self.group_id and self.student.branch_id != self.group.branch_id:
            errors["group"] = _("O'quvchi va guruh turli filiallarga tegishli.")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            errors["end_date"] = _("Tugash sanasi boshlanishdan oldin bo'lmasligi kerak.")
        if self.discount_percent and not (0 <= self.discount_percent <= 100):
            errors["discount_percent"] = _("Chegirma 0-100 orasida bo'lishi kerak.")
        if errors:
            raise ValidationError(errors)

    # -- fee logic ---------------------------------------------------------
    @property
    def base_fee(self) -> Decimal:
        if self.monthly_fee is not None:
            return Decimal(self.monthly_fee)
        if self.group_id and self.group.effective_fee is not None:
            return Decimal(self.group.effective_fee)
        return Decimal("0")

    @property
    def total_discount_percent(self) -> Decimal:
        percent = Decimal(self.discount_percent or 0)
        if self.student_id:
            percent += Decimal(self.student.discount_percent or 0)
        if self.discount_id and self.discount:
            if self.discount.discount_type == "percent":
                percent += Decimal(self.discount.value or 0)
        return min(percent, Decimal(100))

    @property
    def final_fee(self) -> Decimal:
        base = self.base_fee
        percent = self.total_discount_percent
        if not percent:
            return base
        return (base * (Decimal(100) - percent) / Decimal(100)).quantize(Decimal("0.01"))

    @property
    def duration_days(self) -> int:
        end = self.end_date or timezone.localdate()
        return max((end - self.start_date).days, 0)

    @property
    def is_active_enrollment(self) -> bool:
        return self.is_active and self.status == EnrollmentStatus.ACTIVE
