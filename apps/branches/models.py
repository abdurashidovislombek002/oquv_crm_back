"""Branch & Room models."""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel
from common.querysets import RoleScopedQuerySet


class BranchQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "BranchQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "BranchQuerySet":
        return self

    def scope_branch_admin(self, user) -> "BranchQuerySet":
        return self.filter(pk=user.branch_id)

    def scope_manager(self, user) -> "BranchQuerySet":
        return self.filter(pk=user.branch_id)

    def scope_teacher(self, user) -> "BranchQuerySet":
        return self.filter(pk=user.branch_id)

    def scope_student(self, user) -> "BranchQuerySet":
        return self.filter(pk=user.branch_id)

    def scope_parent(self, user) -> "BranchQuerySet":
        return self.filter(pk=user.branch_id)


class RoomQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "RoomQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "RoomQuerySet":
        return self

    def scope_branch_admin(self, user) -> "RoomQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_manager(self, user) -> "RoomQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_teacher(self, user) -> "RoomQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_student(self, user) -> "RoomQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_parent(self, user) -> "RoomQuerySet":
        return self.filter(branch_id=user.branch_id)

    def free_rooms(self):
        return self.filter(branch__isnull=False)


class Branch(BaseModel):
    """An education centre location."""

    name = models.CharField(_("name"), max_length=150, unique=True)
    code = models.CharField(_("code"), max_length=20, unique=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    district = models.CharField(_("district"), max_length=120, blank=True)
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    email = models.EmailField(_("email"), blank=True)
    director_name = models.CharField(_("director"), max_length=150, blank=True)
    working_hours_from = models.TimeField(_("opens at"), null=True, blank=True)
    working_hours_to = models.TimeField(_("closes at"), null=True, blank=True)
    is_head_office = models.BooleanField(_("head office"), default=False)
    description = models.TextField(_("description"), blank=True)
    map_url = models.URLField(_("map url"), blank=True)

    objects = models.Manager()
    active = BranchQuerySet.as_manager()

    class Meta:
        db_table = "branches_branch"
        verbose_name = _("Filial")
        verbose_name_plural = _("Filiallar")
        ordering = ("name",)
        indexes = [models.Index(fields=["code"], name="idx_branch_code")]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @property
    def room_count(self) -> int:
        return self.rooms.filter(is_active=True).count()

    @property
    def group_count(self) -> int:
        return self.groups.filter(is_active=True).count()

    @property
    def student_count(self) -> int:
        return self.students.filter(is_active=True).count()


class RoomType(models.TextChoices):
    CLASSROOM = "classroom", _("Dars xonasi")
    LAB = "lab", _("Laboratoriya")
    GYM = "gym", _("Zal")
    ONLINE = "online", _("Onlayn")
    OTHER = "other", _("Boshqa")


class Room(BaseModel):
    """A physical (or virtual) classroom inside a branch."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rooms", verbose_name=_("branch"))
    name = models.CharField(_("name"), max_length=120)
    code = models.CharField(_("code"), max_length=20, blank=True)
    room_type = models.CharField(
        _("room type"), max_length=20, choices=RoomType.choices, default=RoomType.CLASSROOM
    )
    capacity = models.PositiveSmallIntegerField(_("capacity"), default=15)
    floor = models.CharField(_("floor"), max_length=20, blank=True)
    has_projector = models.BooleanField(_("projector"), default=False)
    has_whiteboard = models.BooleanField(_("whiteboard"), default=True)
    has_ac = models.BooleanField(_("air conditioning"), default=True)
    notes = models.TextField(_("notes"), blank=True)

    objects = models.Manager()
    active = RoomQuerySet.as_manager()

    class Meta:
        db_table = "branches_room"
        verbose_name = _("Xona")
        verbose_name_plural = _("Xonalar")
        ordering = ("branch__name", "name")
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="uniq_room_name_per_branch"),
        ]
        indexes = [models.Index(fields=["branch", "is_active"], name="idx_room_branch_active")]

    def __str__(self) -> str:
        return f"{self.name} — {self.branch.name}"

    @property
    def is_free_capacity(self) -> int:
        return max(self.capacity - self.groups.filter(is_active=True).count(), 0)
