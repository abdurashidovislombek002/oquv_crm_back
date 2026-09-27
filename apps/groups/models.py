"""Group, GroupTeacher and weekly schedule models."""
from __future__ import annotations

from typing import Any, Dict, List

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _

from apps.accounts.constants import Role
from apps.accounts.models import User
from common.constants import WEEKDAY_CHOICES, time_to_minutes
from common.models import BaseModel
from common.querysets import ActiveQuerySet, RoleScopedQuerySet


class GroupStatus(models.TextChoices):
    PLANNED = "planned", _("Rejalashtirilgan")
    ACTIVE = "active", _("Faol")
    PAUSED = "paused", _("To'xtatilgan")
    FINISHED = "finished", _("Tugagan")
    ARCHIVED = "archived", _("Arxiv")


class GroupQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "GroupQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "GroupQuerySet":
        return self

    def scope_branch_admin(self, user) -> "GroupQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_manager(self, user) -> "GroupQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_teacher(self, user) -> "GroupQuerySet":
        return self.filter(Q(teachers=user) | Q(created_by=user)).distinct()

    def scope_student(self, user) -> "GroupQuerySet":
        return self.filter(
            enrollments__student__user=user,
            enrollments__status__in=["active", "paused"],
        ).distinct()

    def scope_parent(self, user) -> "GroupQuerySet":
        return self.filter(
            enrollments__student__parents=user,
            enrollments__status__in=["active", "paused"],
        ).distinct()

    def with_related(self) -> "GroupQuerySet":
        return self.select_related("branch", "course", "level", "room", "created_by").prefetch_related(
            "teachers", "schedule"
        )

    def with_counts(self) -> "GroupQuerySet":
        return self.annotate(
            students_count=Count(
                "enrollments",
                filter=Q(enrollments__is_active=True, enrollments__status="active"),
                distinct=True,
            )
        )


class Group(BaseModel):
    """A study group: one course level, one room, one or more teachers."""

    name = models.CharField(_("name"), max_length=150)
    code = models.CharField(_("code"), max_length=30, blank=True, db_index=True)
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="groups", verbose_name=_("branch")
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.PROTECT, related_name="groups", verbose_name=_("course")
    )
    level = models.ForeignKey(
        "courses.CourseLevel", on_delete=models.PROTECT, related_name="groups", verbose_name=_("level")
    )
    room = models.ForeignKey(
        "branches.Room",
        on_delete=models.SET_NULL,
        related_name="groups",
        null=True,
        blank=True,
        verbose_name=_("room"),
    )
    teachers = models.ManyToManyField(
        User, related_name="teaching_groups", blank=True,
        limit_choices_to={"role": Role.TEACHER, "is_active": True},
        verbose_name=_("teachers"),
    )
    head_teacher = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="head_groups", null=True, blank=True,
        limit_choices_to={"role__in": [Role.TEACHER, Role.MANAGER]}, verbose_name=_("lead teacher"),
    )
    status = models.CharField(
        _("status"), max_length=20, choices=GroupStatus.choices, default=GroupStatus.PLANNED, db_index=True
    )
    capacity = models.PositiveSmallIntegerField(_("capacity"), default=15)
    min_students = models.PositiveSmallIntegerField(_("min students to start"), default=1)
    start_date = models.DateField(_("start date"), null=True, blank=True)
    end_date = models.DateField(_("end date"), null=True, blank=True)
    start_time = models.TimeField(_("start time"), default="16:00")
    end_time = models.TimeField(_("end time"), default="17:00")
    monthly_fee = models.DecimalField(
        _("monthly fee"), max_digits=12, decimal_places=2, null=True, blank=True,
        help_text=_("Bo'sh bo'lsa level narxi qo'llaniladi"),
    )
    description = models.TextField(_("description"), blank=True)
    color = models.CharField(_("color"), max_length=9, blank=True, help_text="#RRGGBB")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_groups",
        verbose_name=_("created by"),
    )

    objects = models.Manager()
    active = GroupQuerySet.as_manager()

    class Meta:
        db_table = "groups_group"
        verbose_name = _("Guruh")
        verbose_name_plural = _("Guruhlar")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["branch", "status"], name="idx_group_branch_status"),
            models.Index(fields=["course", "level"], name="idx_group_course_level"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.branch.name})"

    def clean(self) -> None:
        errors: Dict[str, str] = {}
        if self.start_date and self.end_date and self.start_date > self.end_date:
            errors["end_date"] = _("Tugash sanasi boshlanishdan oldin bo'lmasligi kerak.")
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = _("Tugash vaqti boshlanishdan keyin bo'lishi kerak.")
        if self.room_id and self.branch_id and self.room.branch_id != self.branch_id:
            errors["room"] = _("Xona boshqa filialga tegishli.")
        if self.level_id and self.course_id and self.level.course_id != self.course_id:
            errors["level"] = _("Daraja boshqa kursga tegishli.")
        if self.capacity and self.min_students and self.min_students > self.capacity:
            errors["min_students"] = _("Minimal o'quvchi soni sig'imdan katta bo'lmasligi kerak.")
        if errors:
            raise ValidationError(errors)

    # -- computed ----------------------------------------------------------
    @property
    def effective_fee(self):
        if self.monthly_fee is not None:
            return self.monthly_fee
        return self.level.price if self.level_id else None

    @property
    def filled_seats(self) -> int:
        cached = getattr(self, "students_count", None)
        if cached is not None:
            return cached
        return self.enrollments.filter(is_active=True, status="active").count()

    @property
    def free_seats(self) -> int:
        return max(self.capacity - self.filled_seats, 0)

    @property
    def is_full(self) -> bool:
        return self.filled_seats >= self.capacity

    @property
    def fill_rate(self) -> float:
        if not self.capacity:
            return 0.0
        return round(self.filled_seats / self.capacity * 100, 2)

    @property
    def can_start(self) -> bool:
        return self.filled_seats >= self.min_students

    @property
    def teacher_names(self) -> str:
        return ", ".join(user.full_name for user in self.teachers.all())

    @property
    def schedule_summary(self) -> str:
        days = [str(day.get_day_of_week_display()) for day in self.schedule.all()]
        return f"{', '.join(days)} {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}" \
            if days else f"{self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}"

    @property
    def weekly_lessons_count(self) -> int:
        return self.schedule.count() or 1


class GroupSchedule(BaseModel):
    """Weekly timetable row: which weekday(s), what time."""

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="schedule",
                              verbose_name=_("group"))
    day_of_week = models.PositiveSmallIntegerField(_("day of week"), choices=WEEKDAY_CHOICES)
    start_time = models.TimeField(_("start time"))
    end_time = models.TimeField(_("end time"))
    room = models.ForeignKey(
        "branches.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="schedules",
        verbose_name=_("room"),
    )
    is_active_slot = models.BooleanField(_("active slot"), default=True)

    objects = models.Manager()
    active = ActiveQuerySet.as_manager()

    class Meta:
        db_table = "groups_group_schedule"
        verbose_name = _("Jadval")
        verbose_name_plural = _("Jadval qatorlari")
        ordering = ("day_of_week", "start_time")
        constraints = [
            models.UniqueConstraint(
                fields=["group", "day_of_week", "start_time"], name="uniq_group_slot_per_day"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.group.name} — {self.get_day_of_week_display()} {self.start_time:%H:%M}"

    def clean(self) -> None:
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError({"end_time": _("Tugash vaqti boshlanishdan keyin bo'lishi kerak.")})

    @property
    def duration_minutes(self) -> int:
        start = time_to_minutes(self.start_time) or 0
        end = time_to_minutes(self.end_time) or 0
        return max(end - start, 0)

    @property
    def time_range(self) -> str:
        return f"{self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}"
