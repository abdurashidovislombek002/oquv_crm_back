"""Celery tasks for notifications and periodic CRM jobs."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="notifications.send_notification", bind=True, max_retries=3, default_retry_delay=60)
def send_notification_task(self, notification_id: int) -> Dict[str, Any]:
    """Sends a single notification (scheduled or immediate)."""
    from .models import Notification, NotificationStatus
    from .services import NotificationService

    notification = Notification.objects.filter(pk=notification_id).first()
    if notification is None:
        logger.warning("Notification %s not found", notification_id)
        return {"status": "missing", "id": notification_id}
    if notification.status == NotificationStatus.SENT:
        return {"status": "already_sent", "id": notification_id}
    if notification.status == NotificationStatus.CANCELED:
        return {"status": "canceled", "id": notification_id}

    result = NotificationService.deliver(notification)
    if result.status == NotificationStatus.FAILED and self.request.retries < self.max_retries:
        raise self.retry(exc=RuntimeError(result.error_message or "delivery failed"))
    return {"status": result.status, "id": notification_id, "error": result.error_message}


@shared_task(name="notifications.send_bulk")
def send_bulk_task(notification_ids: List[int]) -> Dict[str, Any]:
    results = [send_notification_task(notification_id) for notification_id in notification_ids]
    sent = sum(1 for item in results if item.get("status") == "sent")
    return {"total": len(results), "sent": sent, "results": results}


@shared_task(name="notifications.scan_due_follow_ups")
def scan_due_follow_ups() -> Dict[str, Any]:
    """Creates reminder notifications for due lead follow-ups."""
    from apps.crm_leads.models import FollowUpStatus, LeadFollowUp
    from .services import NotificationService

    due = LeadFollowUp.objects.filter(
        status=FollowUpStatus.PENDING, due_at__lte=timezone.now()
    ).select_related("lead", "assigned_to")
    created = 0
    for follow_up in due:
        already = follow_up.lead.notifications.filter(
            related_object=follow_up, status__in=["pending", "queued", "sent"]
        ).exists()
        if already:
            continue
        NotificationService.create_for_lead_follow_up(follow_up)
        created += 1
    return {"due": due.count(), "notifications_created": created}


@shared_task(name="notifications.daily_digest")
def daily_digest() -> Dict[str, Any]:
    """Sends managers a daily summary of lessons, new leads and debts."""
    from django.contrib.contenttypes.models import ContentType

    from apps.attendance.models import Lesson
    from apps.crm_leads.models import Lead, LeadStatus
    from apps.payments.models import Debt
    from .models import Notification
    from .services import NotificationService

    today = timezone.localdate()
    lessons = Lesson.active.filter(date=today).count()
    new_leads = Lead.active.filter(created_at__date=today).count()
    converted = Lead.active.filter(
        status=LeadStatus.CONVERTED, converted_at__date=today
    ).count()
    debtors = Debt.active.filter(status__in=["unpaid", "partial", "overdue"]).count()

    from apps.accounts.constants import Role
    from apps.accounts.models import User

    managers = User.objects.filter(role__in=[Role.SUPER_ADMIN, Role.BRANCH_ADMIN, Role.MANAGER],
                                    is_active=True)
    created = 0
    for manager in managers:
        NotificationService.create(
            {
                "branch": manager.branch,
                "recipient": manager,
                "channel": "in_app",
                "subject": f"Kunlik hisobot: {today:%Y-%m-%d}",
                "body": (
                    f"Darslar: {lessons}\nYangi leadlar: {new_leads}\n"
                    f"O'quvchiga aylanganlar: {converted}\nQarzdor o'quvchilar: {debtors}"
                ),
                "content_type": ContentType.objects.get_for_model(Lesson),
            },
            send_now=True,
            schedule_task=False,
        )
        created += 1
    return {"managers_notified": created}


@shared_task(name="notifications.cleanup_old")
def cleanup_old(days: int = 180) -> Dict[str, Any]:
    """Hard-deletes old notification rows to keep the table small."""
    from .models import Notification

    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = Notification.objects.filter(
        created_at__lt=cutoff, status__in=["sent", "canceled", "failed"]
    ).delete()
    return {"deleted": deleted}
