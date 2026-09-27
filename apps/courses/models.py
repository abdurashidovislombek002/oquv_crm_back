"""Course -> CourseLevel catalog (any subject: maths, robotics, chess, ...)."""
from __future__ import annotations

from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel
from common.querysets import RoleScopedQuerySet


class CourseQuerySet(RoleScopedQuerySet):
    """The catalog is global: every authenticated role can read it."""

    def scope_default(self, user) -> "CourseQuerySet":
        return self

    scope_all = scope_default

    def with_levels(self) -> "CourseQuerySet":
        return self.prefetch_related("levels")


class Course(BaseModel):
    """A subject / course. Levels ( Beginner -> Advanced ) live in ``CourseLevel``."""

    name = models.CharField(_("name"), max_length=150, unique=True)
    slug = models.SlugField(_("slug"), max_length=180, unique=True, blank=True)
    category = models.CharField(_("category"), max_length=100, blank=True, db_index=True)
    description = models.TextField(_("description"), blank=True)
    goals = models.TextField(_("goals"), blank=True)
    duration_months = models.PositiveSmallIntegerField(_("duration (months)"), default=6)
    lessons_per_week = models.PositiveSmallIntegerField(_("lessons per week"), default=2)
    lesson_duration_minutes = models.PositiveSmallIntegerField(_("lesson minutes"), default=60)
    base_price = models.DecimalField(
        _("base price"), max_digits=12, decimal_places=2, default=0,
        help_text=_("Oylik to'lov (asosiy narx)"),
    )
    min_age = models.PositiveSmallIntegerField(_("min age"), null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(_("max age"), null=True, blank=True)
    cover_url = models.URLField(_("cover url"), blank=True)
    is_featured = models.BooleanField(_("featured"), default=False)
    ordering = models.PositiveSmallIntegerField(_("ordering"), default=0)

    objects = models.Manager()
    active = CourseQuerySet.as_manager()

    class Meta:
        db_table = "courses_course"
        verbose_name = _("Kurs/Fan")
        verbose_name_plural = _("Kurslar/Fanlar")
        ordering = ("ordering", "name")
        indexes = [models.Index(fields=["category", "is_active"], name="idx_course_cat_active")]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            base = slugify(self.name, allow_unicode=True)[:150] or "course"
            slug = base
            counter = 2
            while Course.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def levels_count(self) -> int:
        return self.levels.filter(is_active=True).count()

    @property
    def groups_count(self) -> int:
        return self.groups.filter(is_active=True).count()


class CourseLevel(BaseModel):
    """A level inside a course (e.g. Math -> Beginner / Intermediate / Advanced)."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="levels", verbose_name=_("course")
    )
    name = models.CharField(_("name"), max_length=120)
    slug = models.SlugField(_("slug"), max_length=150, blank=True)
    code = models.CharField(_("code"), max_length=30, blank=True)
    description = models.TextField(_("description"), blank=True)
    price = models.DecimalField(_("price"), max_digits=12, decimal_places=2, default=0)
    duration_months = models.PositiveSmallIntegerField(_("duration (months)"), null=True, blank=True)
    min_students_to_open = models.PositiveSmallIntegerField(_("min students"), default=1)
    max_students_per_group = models.PositiveSmallIntegerField(_("max students per group"), default=15)
    ordering = models.PositiveSmallIntegerField(_("ordering"), default=0)

    objects = models.Manager()
    active = CourseQuerySet.as_manager()

    class Meta:
        db_table = "courses_course_level"
        verbose_name = _("Kurs darajasi")
        verbose_name_plural = _("Kurs darajalari")
        ordering = ("course__ordering", "ordering", "name")
        constraints = [
            models.UniqueConstraint(fields=["course", "name"], name="uniq_level_per_course"),
        ]

    def __str__(self) -> str:
        return f"{self.course.name} — {self.name}"

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)[:120] or "level"
        super().save(*args, **kwargs)

    @property
    def groups_count(self) -> int:
        return self.groups.filter(is_active=True).count()
