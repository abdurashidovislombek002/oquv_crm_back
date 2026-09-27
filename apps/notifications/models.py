"""Notification models: templates + delivery log."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from common.models import BaseModel
from common.querysets import ActiveQuerySet, RoleScopedQuerySet


class NotificationChannel(models.TextChoices):
    SMS = "sms", _("SMS")
    TELEGRAM = "telegram", _("Telegram")
    EMAIL = "email", _("Email")
    PUSH = "push", _("Push")
    IN_APP = "in_app", _("Ilova ichida")


class NotificationStatus(models.TextChoices):
    PENDING = "pending", _("Kutilmoqda")
    QUEUED = "queued", _("Navbatda")
    SENT = "sent", _("Yuborildi")
    FAILED = "failed", _("Xatolik")
    CANCELED = "canceled", _("Bekor qilindi")


class NotificationPriority(models.TextChoices):
    LOW = "low", _("Past")
    NORMAL = "normal", _("O'rtacha")
    HIGH = "high", _("Yuqori")


class NotificationQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "NotificationQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "NotificationQuerySet":
        return self

    def scope_branch_admin(self, user) -> "NotificationQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_manager(self, user) -> "NotificationQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_teacher(self, user) -> "NotificationQuerySet":
        return self.filter(recipient=user)

    def scope_student(self, user) -> "NotificationQuerySet":
        return self.filter(Q(recipient=user) | Q(student__user=user)).distinct()

    def scope_parent(self, user) -> "NotificationQuerySet":
        return self.filter(Q(recipient=user) | Q(student__parents=user)).distinct()

    def pending(self) -> "NotificationQuerySet":
        return self.filter(status__in=[NotificationStatus.PENDING, NotificationStatus.QUEUED])


class NotificationTemplate(BaseModel):
    """Reusable message body with ``{placeholder}`` variables."""

    key = models.CharField(_("key"), max_length=80, unique=True, db_index=True)
    name = models.CharField(_("name"), max_length=120)
    channel = models.CharField(
        _("channel"), max_length=10, choices=NotificationChannel.choices,
        default=NotificationChannel.SMS,
    )
    subject = models.CharField(_("subject"), max_length=150, blank=True)
    body = models.TextField(_("body"))
    variables = models.JSONField(_("variables"), default=list, blank=True)
    description = models.CharField(_("description"), max_length=255, blank=True)

    objects = models.Manager()
    active = ActiveQuerySet.as_manager()

    class Meta:
        db_table = "notifications_template"
        verbose_name = _("Xabar shabloni")
        verbose_name_plural = _("Xabar shablonlari")
        ordering = ("channel", "key")

    def __str__(self) -> str:
        return f"{self.name} ({self.get_channel_display()})"

    def render(self, context: Optional[Dict[str, Any]] = None) -> str:
        from .services import render_template

        return render_template(self.body, context or {})

    def render_subject(self, context: Optional[Dict[str, Any]] = None) -> str:
        from .services import render_template

        return render_template(self.subject, context or {})


class Notification(BaseModel):
    """A single message and its delivery state."""

    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications", verbose_name=_("branch"),
    )
    channel = models.CharField(
        _("channel"), max_length=10, choices=NotificationChannel.choices,
        default=NotificationChannel.SMS, db_index=True,
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications",
        verbose_name=_("recipient"),
    )
    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications", verbose_name=_("student"),
    )
    lead = models.ForeignKey(
        "crm_leads.Lead", on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications", verbose_name=_("lead"),
    )
    template = models.ForeignKey(
        NotificationTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications", verbose_name=_("template"),
    )
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    email = models.EmailField(_("email"), blank=True)
    telegram_id = models.CharField(_("telegram id"), max_length=64, blank=True)
    subject = models.CharField(_("subject"), max_length=150, blank=True)
    body = models.TextField(_("body"), blank=True)
    status = models.CharField(
        _("status"), max_length=10, choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING, db_index=True,
    )
    priority = models.CharField(
        _("priority"), max_length=6, choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
    )
    scheduled_at = models.DateTimeField(_("scheduled at"), default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(_("attempts"), default=0)
    error_message = models.TextField(_("error"), blank=True)
    provider_message_id = models.CharField(_("provider id"), max_length=100, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_notifications",
        verbose_name=_("created by"),
    )
    # generic link to any business object (lesson, payment, lead follow-up, ...)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name=_("content type"),
    )
    object_id = models.PositiveBigIntegerField(_("object id"), null=True, blank=True)
    related_object = GenericForeignKey("content_type", "object_id")

    objects = models.Manager()
    active = NotificationQuerySet.as_manager()

    class Meta:
        db_table = "notifications_notification"
        verbose_name = _("Bildirishnoma")
        verbose_name_plural = _("Bildirishnomalar")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "scheduled_at"], name="idx_notif_status_sched"),
            models.Index(fields=["channel", "status"], name="idx_notif_channel_status"),
        ]

    def __str__(self) -> str:
        return f"[{self.get_channel_display()}] {self.subject or self.body[:40]} ({self.status})"

    # -- computed ----------------------------------------------------------
    @property
    def is_sent(self) -> bool:
        return self.status == NotificationStatus.SENT

    @property
    def is_pending(self) -> bool:
        return self.status in (NotificationStatus.PENDING, NotificationStatus.QUEUED)

    @property
    def target_address(self) -> str:
        return {
            NotificationChannel.SMS: self.phone,
            NotificationChannel.EMAIL: self.email,
            NotificationChannel.TELEGRAM: self.telegram_id or self.phone,
        }.get(self.channel, "")

    def mark_sent(self, provider_id: str = "") -> "Notification":
        self.status = NotificationStatus.SENT
        self.sent_at = timezone.now()
        self.error_message = ""
        self.provider_message_id = provider_id
        self.attempts += 1
        self.save(update_fields=["status", "sent_at", "error_message", "provider_message_id",
                                  "attempts", "updated_at"])
        return self

    def mark_failed(self, error: str) -> "Notification":
        self.status = NotificationStatus.FAILED
        self.error_message = str(error)[:2000]
        self.attempts += 1
        self.save(update_fields=["status", "error_message", "attempts", "updated_at"])
        return self
