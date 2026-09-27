"""Notification business logic + Celery dispatch."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.models import User
from common.exceptions import BusinessRuleError, NotFoundError
from common.services import BaseService

from .models import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    NotificationTemplate,
)
from .senders import get_sender

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def render_template(body: str, context: Dict[str, Any]) -> str:
    """Replaces ``{name}`` placeholders; unknown keys are left untouched."""
    def replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        value = context.get(key)
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, body or "")


class NotificationService(BaseService):
    model = Notification

    # -- creation ----------------------------------------------------------
    @classmethod
    def create(
        cls,
        data: Dict[str, Any],
        *,
        actor: Optional[User] = None,
        send_now: bool = False,
        schedule_task: bool = True,
    ) -> Notification:
        payload = dict(data)
        template = payload.pop("template", None)
        context = payload.pop("context", None) or {}

        if isinstance(template, str):
            template = NotificationTemplate.active.filter(key=template, is_active=True).first()
        if template is None:
            template_key = payload.pop("template_key", None)
            if template_key:
                template = NotificationTemplate.active.filter(
                    key=template_key, is_active=True
                ).first()
        payload["template"] = template

        if template is not None:
            payload.setdefault("subject", render_template(template.subject, context))
            payload.setdefault("body", render_template(template.body, context))
            if not payload.get("channel"):
                payload["channel"] = template.channel

        channel = payload.get("channel") or NotificationChannel.SMS
        payload["channel"] = channel
        if not payload.get("body"):
            raise BusinessRuleError(detail="Xabar matni bo'sh bo'lmasligi kerak.", code="empty_body")

        recipient = payload.get("recipient")
        student = payload.get("student")
        if channel == NotificationChannel.EMAIL and not payload.get("email"):
            payload["email"] = getattr(recipient, "email", "") or getattr(student, "email", "")
        if channel in (NotificationChannel.SMS, NotificationChannel.TELEGRAM) and not payload.get("phone"):
            payload["phone"] = getattr(student, "phone", "") or getattr(recipient, "phone", "")
        if channel == NotificationChannel.TELEGRAM and not payload.get("telegram_id"):
            payload["telegram_id"] = (
                getattr(student, "telegram_id", "")
                or getattr(recipient, "telegram_id", "")
            )

        scheduled_at = payload.pop("scheduled_at", None)
        if isinstance(scheduled_at, str):
            scheduled_at = parse_datetime(scheduled_at)
        payload["scheduled_at"] = scheduled_at or timezone.now()
        payload["created_by"] = actor

        related = payload.pop("related_object", None)
        if related is not None:
            payload["content_type"] = ContentType.objects.get_for_model(related)
            payload["object_id"] = related.pk

        notification = Notification.objects.create(**payload)
        if send_now:
            cls.send_now(notification.pk)
        elif schedule_task and notification.scheduled_at > timezone.now():
            cls.enqueue(notification)
        return notification

    @classmethod
    def bulk_create(
        cls,
        items: Iterable[Dict[str, Any]],
        *,
        actor: Optional[User] = None,
    ) -> List[Notification]:
        return [cls.create(item, actor=actor) for item in items]

    # -- delivery ----------------------------------------------------------
    @classmethod
    def enqueue(cls, notification: Notification) -> str:
        from .tasks import send_notification_task

        notification.status = NotificationStatus.QUEUED
        notification.save(update_fields=["status", "updated_at"])
        eta = notification.scheduled_at
        async_result = send_notification_task.apply_async(
            args=[notification.pk], eta=eta if eta else None
        )
        return getattr(async_result, "id", "")

    @classmethod
    def send_now(cls, notification_id: int) -> Notification:
        notification = Notification.objects.filter(pk=notification_id).first()
        if notification is None:
            raise NotFoundError(detail="Bildirishnoma topilmadi.")
        return cls.deliver(notification)

    @classmethod
    def deliver(cls, notification: Notification) -> Notification:
        """Synchronous delivery (used by the Celery task and by tests)."""
        address = notification.target_address
        sender = get_sender(notification.channel)
        try:
            provider_id = sender.send(address, notification.subject, notification.body)
        except Exception as exc:  # noqa: BLE001 - failure must be logged on the row
            logger.warning("Notification %s failed: %s", notification.pk, exc)
            return notification.mark_failed(str(exc))
        return notification.mark_sent(provider_id)

    @classmethod
    def cancel(cls, notification: Notification) -> Notification:
        if notification.status == NotificationStatus.SENT:
            raise BusinessRuleError(
                detail="Yuborilgan xabar bekor qilinmaydi.", code="already_sent"
            )
        notification.status = NotificationStatus.CANCELED
        notification.save(update_fields=["status", "updated_at"])
        return notification

    @classmethod
    def retry(cls, notification: Notification) -> Notification:
        if notification.attempts >= 3:
            raise BusinessRuleError(
                detail="3 marta urinishdan keyin qayta yuborib bo'lmaydi.", code="max_attempts"
            )
        notification.status = NotificationStatus.QUEUED
        notification.save(update_fields=["status", "updated_at"])
        return notification

    # -- high level helpers ------------------------------------------------
    @classmethod
    def notify_student_debt(cls, student: Any, debt: Any, *, actor: Optional[User] = None) -> Notification:
        template = NotificationTemplate.active.filter(
            key="debt_reminder", is_active=True
        ).first()
        return cls.create(
            {
                "branch": student.branch,
                "student": student,
                "template": template,
                "channel": template.channel if template else NotificationChannel.SMS,
                "context": {
                    "student": student.full_name,
                    "period": debt.period_month.strftime("%Y-%m"),
                    "amount": debt.remaining,
                    "days_overdue": debt.days_overdue,
                },
                "related_object": debt,
            },
            actor=actor,
        )

    @classmethod
    def create_for_lead_follow_up(cls, follow_up: Any) -> Notification:
        lead = follow_up.lead
        template = NotificationTemplate.active.filter(
            key="lead_follow_up", is_active=True
        ).first()
        return cls.create(
            {
                "branch": lead.branch,
                "lead": lead,
                "recipient": follow_up.assigned_to,
                "template": template,
                "channel": NotificationChannel.IN_APP,
                "context": {
                    "lead": lead.full_name,
                    "phone": lead.phone,
                    "due_at": follow_up.due_at.strftime("%Y-%m-%d %H:%M"),
                },
                "scheduled_at": follow_up.due_at,
                "related_object": follow_up,
            },
        )

    @classmethod
    def notify_lesson_cancellation(cls, lesson: Any, reason: str = "") -> List[Notification]:
        students = list(lesson.group.students.all()) if hasattr(lesson.group, "students") else []
        return cls.bulk_create(
            [
                {
                    "branch": lesson.branch,
                    "student": student,
                    "channel": NotificationChannel.SMS,
                    "subject": "Dars bekor qilindi",
                    "body": (
                        f"{student.full_name}, {lesson.date:%Y-%m-%d} {lesson.start_time:%H:%M} "
                        f"darsi bekor qilindi. {reason}"
                    ),
                    "related_object": lesson,
                }
                for student in students
            ]
        )


class NotificationTemplateService(BaseService):
    model = NotificationTemplate

    @classmethod
    def render(cls, key: str, context: Dict[str, Any]) -> Dict[str, str]:
        template = cls.base_queryset().filter(key=key, is_active=True).first()
        if template is None:
            raise NotFoundError(detail=f"'{key}' shabloni topilmadi.", code="template_not_found")
        return {
            "subject": template.render_subject(context),
            "body": template.render(context),
            "channel": template.channel,
        }

    @classmethod
    def default_templates(cls) -> List[Dict[str, Any]]:
        return [
            {
                "key": "debt_reminder",
                "name": "Qarz eslatmasi",
                "channel": NotificationChannel.SMS,
                "body": "Hurmatli {student}, {period} oy uchun {amount} so'm to'lov qarzingiz mavjud. "
                        "Muddati o'tgan: {days_overdue} kun.",
                "variables": ["student", "period", "amount", "days_overdue"],
            },
            {
                "key": "payment_received",
                "name": "To'lov qabul qilindi",
                "channel": NotificationChannel.SMS,
                "body": "Hurmatli {student}, {amount} so'm to'lov qabul qilindi. Qarz: {debt} so'm.",
                "variables": ["student", "amount", "debt"],
            },
            {
                "key": "lesson_reminder",
                "name": "Dars eslatmasi",
                "channel": NotificationChannel.SMS,
                "body": "Hurmatli {student}, bugun {time} da {course} fanidan dars bor.",
                "variables": ["student", "time", "course"],
            },
            {
                "key": "lead_follow_up",
                "name": "Lead follow-up eslatmasi",
                "channel": NotificationChannel.IN_APP,
                "body": "{lead} ({phone}) bilan {due_at} da bog'lanish kerak.",
                "variables": ["lead", "phone", "due_at"],
            },
            {
                "key": "attendance_absent",
                "name": "Kelmaganlik xabari",
                "channel": NotificationChannel.EMAIL,
                "subject": "Darsga kelmaganlik",
                "body": "Hurmatli ota-ona, {student} {date} sanasidagi darsga kelmadi.",
                "variables": ["student", "date"],
            },
        ]
