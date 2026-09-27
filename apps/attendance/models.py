"""Lesson (dars) and per-student attendance records."""
from __future__ import annotations

from typing import Any, Dict, List

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from common.models import BaseModel
from common.querysets import ActiveQuerySet, RoleScopedQuerySet


class LessonStatus(models.TextChoices):
    SCHEDULED = "scheduled", _("Rejalashtirilgan")
    HELD = "held", _("O'tkazildi")
    CANCELED = "canceled", _("Bekor qilindi")


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", _("Keldi")
    ABSENT = "absent", _("Kelmadi")
    LATE = "late", _("Kechikdi")
    EXCUSED = "excused", _("Sababli kelmadi")
    ONLINE = "online", _("Onlayn ishladi")


class LessonQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "LessonQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "LessonQuerySet":
        return self

    def scope_branch_admin(self, user) -> "LessonQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_manager(self, user) -> "LessonQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_teacher(self, user) -> "LessonQuerySet":
        return self.filter(
            Q(teacher=user) | Q(group__teachers=user) | Q(group__head_teacher=user)
        ).distinct()

    def scope_student(self, user) -> "LessonQuerySet":
        return self.filter(
            group__enrollments__student__user=user,
            group__enrollments__is_active=True,
        ).distinct()

    def scope_parent(self, user) -> "LessonQuerySet":
        return self.filter(
            group__enrollments__student__parents=user,
            group__enrollments__is_active=True,
        ).distinct()

    def with_related(self) -> "LessonQuerySet":
        return self.select_related("group", "group__course", "branch", "room", "teacher",
                                   "created_by")

    def with_counts(self) -> "LessonQuerySet":
        return self.annotate(
            present_count=Count(
                "records", filter=Q(records__status=AttendanceStatus.PRESENT), distinct=True
            ),
            absent_count=Count(
                "records", filter=Q(records__status=AttendanceStatus.ABSENT), distinct=True
            ),
            records_total=Count("records", distinct=True),
        )


class Lesson(BaseModel):
    """A single scheduled/held lesson of a group."""

    group = models.ForeignKey(
        "groups.Group", on_delete=models.CASCADE, related_name="lessons", verbose_name=_("group")
    )
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.CASCADE, related_name="lessons", verbose_name=_("branch")
    )
    date = models.DateField(_("date"), db_index=True)
    start_time = models.TimeField(_("start time"))
    end_time = models.TimeField(_("end time"))
    room = models.ForeignKey(
        "branches.Room", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lessons", verbose_name=_("room"),
    )
    teacher = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons_taught",
        limit_choices_to={"role__in": ["teacher", "manager", "branch_admin"]},
        verbose_name=_("teacher"),
    )
    topic = models.CharField(_("topic"), max_length=200, blank=True)
    status = models.CharField(
        _("status"), max_length=12, choices=LessonStatus.choices, default=LessonStatus.SCHEDULED,
        db_index=True,
    )
    homework = models.TextField(_("homework"), blank=True)
    is_generated = models.BooleanField(_("generated from schedule"), default=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_lessons",
        verbose_name=_("created by"),
    )

    objects = models.Manager()
    active = LessonQuerySet.as_manager()

    class Meta:
        db_table = "attendance_lesson"
        verbose_name = _("Dars")
        verbose_name_plural = _("Darslar")
        ordering = ("-date", "start_time")
        constraints = [
            models.UniqueConstraint(
                fields=["group", "date", "start_time"], name="uniq_lesson_per_group_slot"
            ),
        ]
        indexes = [
            models.Index(fields=["branch", "date"], name="idx_lesson_branch_date"),
            models.Index(fields=["group", "date"], name="idx_lesson_group_date"),
        ]

    def __str__(self) -> str:
        return f"{self.group.name} — {self.date:%Y-%m-%d} {self.start_time:%H:%M}"

    def clean(self) -> None:
        errors: Dict[str, str] = {}
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = _("Tugash vaqti boshlanishdan keyin bo'lishi kerak.")
        if self.group_id and self.branch_id and self.group.branch_id != self.branch_id:
            errors["branch"] = _("Filial guruh bilan mos kelmaydi.")
        if errors:
            raise ValidationError(errors)

    # -- computed ----------------------------------------------------------
    @property
    def duration_minutes(self) -> int:
        from common.utils import time_to_minutes

        start = time_to_minutes(self.start_time) or 0
        end = time_to_minutes(self.end_time) or 0
        return max(end - start, 0)

    @property
    def students_count(self) -> int:
        cached = getattr(self, "records_total", None)
        return cached if cached is not None else self.records.count()

    @property
    def attendance_rate(self) -> float:
        total = self.students_count
        if not total:
            return 0.0
        present = getattr(self, "present_count", None)
        if present is None:
            present = self.records.filter(
                status__in=[AttendanceStatus.PRESENT, AttendanceStatus.ONLINE]
            ).count()
        return round(present / total * 100, 2)

    @property
    def is_marked(self) -> bool:
        return self.records.filter(is_active=True).exists()


class AttendanceRecord(BaseModel):
    """Keldi / kelmadi / kechikdi for a single student in a lesson."""

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="records", verbose_name=_("lesson")
    )
    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="attendance_records",
        verbose_name=_("student"),
    )
    status = models.CharField(
        _("status"), max_length=10, choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT, db_index=True,
    )
    marked_at = models.DateTimeField(_("marked at"), default=timezone.now)
    marked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="marked_attendance",
        verbose_name=_("marked by"),
    )
    note = models.CharField(_("note"), max_length=255, blank=True)
    minutes_late = models.PositiveSmallIntegerField(_("minutes late"), default=0)

    objects = models.Manager()
    active = ActiveQuerySet.as_manager()

    class Meta:
        db_table = "attendance_record"
        verbose_name = _("Davomat")
        verbose_name_plural = _("Davomat qatorlari")
        ordering = ("lesson__date", "student__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=["lesson", "student"], name="uniq_attendance_per_lesson_student"
            ),
        ]
        indexes = [models.Index(fields=["student", "status"], name="idx_attendance_student_status")]

    def __str__(self) -> str:
        return f"{self.student_id} @ {self.lesson_id}: {self.get_status_display()}"

    @property
    def is_present(self) -> bool:
        return self.status in (AttendanceStatus.PRESENT, AttendanceStatus.ONLINE)
