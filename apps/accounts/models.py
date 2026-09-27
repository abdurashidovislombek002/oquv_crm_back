"""Custom user model with CRM roles and multi-branch affiliation."""
from __future__ import annotations

from typing import Any, Optional

from django.contrib.auth.models import AbstractUser, BaseUserManager, UserManager as DjangoUserManager
from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel, TimeStampedModel
from common.querysets import RoleScopedQuerySet
from common.utils import format_phone

from .constants import MANAGEMENT_ROLES, TEACHING_ROLES, Role


class UserQuerySet(RoleScopedQuerySet):
    """Visibility rules for the user directory."""

    def scope_default(self, user) -> "UserQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "UserQuerySet":
        return self

    def scope_branch_admin(self, user) -> "UserQuerySet":
        return self.filter(branch_id=user.branch_id).exclude(role=Role.SUPER_ADMIN)

    def scope_manager(self, user) -> "UserQuerySet":
        return self.filter(branch_id=user.branch_id).filter(
            role__in=[Role.BRANCH_ADMIN, Role.MANAGER, Role.TEACHER]
        )

    def scope_teacher(self, user) -> "UserQuerySet":
        return self.filter(pk=user.pk)

    def scope_student(self, user) -> "UserQuerySet":
        return self.filter(pk=user.pk)

    def scope_parent(self, user) -> "UserQuerySet":
        return self.filter(pk=user.pk)


class UserManager(DjangoUserManager):
    """Manager with CRM specific creation helpers."""

    def get_queryset(self) -> UserQuerySet:
        return UserQuerySet(self.model, using=self._db).filter(is_active=True)

    def with_inactive(self) -> UserQuerySet:
        return UserQuerySet(self.model, using=self._db)

    def create_user(
        self,
        username: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        **extra_fields: Any,
    ) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        if extra_fields.get("role") in (Role.SUPER_ADMIN, Role.BRANCH_ADMIN):
            extra_fields["is_staff"] = True
        if extra_fields.get("role") == Role.SUPER_ADMIN:
            extra_fields["is_superuser"] = True
        user = self.model(username=username, email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        username: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        **extra_fields: Any,
    ) -> "User":
        extra_fields["role"] = Role.SUPER_ADMIN
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self.create_user(username, email, password, **extra_fields)

    def teachers_of_branch(self, branch_id: Optional[int]) -> UserQuerySet:
        return self.filter(role=Role.TEACHER, branch_id=branch_id)


class User(AbstractUser):
    """AbstractUser + role, branch, phone, telegram id."""

    email = models.EmailField(_("email address"), blank=True, null=True, db_index=True)
    first_name = models.CharField(_("first name"), max_length=150, blank=True)
    last_name = models.CharField(_("last name"), max_length=150, blank=True)
    middle_name = models.CharField(_("middle name"), max_length=150, blank=True)

    role = models.CharField(
        _("role"), max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.SET_NULL,
        related_name="users",
        null=True,
        blank=True,
        verbose_name=_("branch"),
    )
    phone = models.CharField(_("phone"), max_length=32, blank=True, db_index=True)
    telegram_id = models.CharField(_("telegram id"), max_length=64, blank=True, db_index=True)
    avatar_url = models.URLField(_("avatar url"), blank=True)
    birth_date = models.DateField(_("birth date"), null=True, blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    is_active = models.BooleanField(_("is active"), default=True, db_index=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        db_table = "accounts_user"
        verbose_name = _("Foydalanuvchi")
        verbose_name_plural = _("Foydalanuvchilar")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["role", "branch"], name="idx_user_role_branch"),
            models.Index(fields=["phone"], name="idx_user_phone"),
        ]

    def __str__(self) -> str:
        return self.full_name or self.username

    def save(self, *args, **kwargs) -> None:
        if self.phone:
            self.phone = format_phone(self.phone)
        super().save(*args, **kwargs)

    # -- helpers -----------------------------------------------------------
    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(part for part in parts if part).strip() or self.username

    @property
    def initials(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        if parts:
            return "".join(part[0].upper() for part in parts[:2])
        return (self.username or "?")[:2].upper()

    @property
    def is_management(self) -> bool:
        return self.is_superuser or self.role in MANAGEMENT_ROLES

    @property
    def is_teaching_staff(self) -> bool:
        return self.is_superuser or self.role in TEACHING_ROLES

    @property
    def is_teacher(self) -> bool:
        return self.role == Role.TEACHER

    @property
    def is_student_role(self) -> bool:
        return self.role == Role.STUDENT

    @property
    def is_parent(self) -> bool:
        return self.role == Role.PARENT

    @property
    def branch_name(self) -> str:
        return self.branch.name if self.branch_id else ""

    def has_role(self, *roles: str) -> bool:
        if self.is_superuser:
            return True
        return self.role in roles

    def can_access_branch(self, branch_id: Optional[int]) -> bool:
        if self.is_superuser or self.role == Role.SUPER_ADMIN:
            return True
        if branch_id is None:
            return True
        return self.branch_id == branch_id

    def record_login(self, ip: Optional[str] = None) -> None:
        self.last_login = timezone.now()
        if ip:
            self.last_login_ip = ip
        self.save(update_fields=["last_login", "last_login_ip"])


class UserActivity(TimeStampedModel):
    """Light-weight audit trail (last login, password change, ...)."""

    class Action(models.TextChoices):
        LOGIN = "login", _("Kirish")
        LOGOUT = "logout", _("Chiqish")
        PASSWORD_CHANGE = "password_change", _("Parol o'zgartirildi")
        CREATED = "created", _("Yaratildi")
        UPDATED = "updated", _("Yangilandi")
        DELETED = "deleted", _("O'chirildi")

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activities")
    action = models.CharField(max_length=30, choices=Action.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "accounts_user_activity"
        ordering = ("-created_at",)
        verbose_name = _("Foydalanuvchi faolligi")

    def __str__(self) -> str:
        return f"{self.user} — {self.get_action_display()}"
