"""Lead business logic: pipeline, follow-ups and conversion to a student."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import User
from common.exceptions import BusinessRuleError, NotFoundError
from common.services import BaseService

from .models import (
    FollowUpStatus,
    Lead,
    LeadCall,
    LeadNote,
    LeadStatus,
    LeadStatusHistory,
    LeadFollowUp,
)


class LeadService(BaseService):
    model = Lead

    #: allowed kanban transitions
    ALLOWED_TRANSITIONS: Dict[str, List[str]] = {
        LeadStatus.NEW: [LeadStatus.CONTACTED, LeadStatus.TRIAL_SCHEDULED, LeadStatus.REJECTED,
                         LeadStatus.CONVERTED],
        LeadStatus.CONTACTED: [LeadStatus.TRIAL_SCHEDULED, LeadStatus.REJECTED, LeadStatus.CONVERTED],
        LeadStatus.TRIAL_SCHEDULED: [LeadStatus.TRIAL_DONE, LeadStatus.REJECTED, LeadStatus.CONVERTED],
        LeadStatus.TRIAL_DONE: [LeadStatus.CONVERTED, LeadStatus.REJECTED],
        LeadStatus.CONVERTED: [],
        LeadStatus.REJECTED: [LeadStatus.NEW, LeadStatus.CONTACTED],
    }

    @classmethod
    @transaction.atomic
    def create_lead(cls, data: Dict[str, Any], *, actor: Optional[User] = None) -> Lead:
        payload = cls.cleanup(data)
        branch = payload.get("branch") or (actor.branch if actor else None)
        if branch is None:
            raise BusinessRuleError(detail="Filial tanlash majburiy.", code="branch_required")
        payload["branch"] = branch
        level = payload.get("level")
        course = payload.get("course") or (level.course if level else None)
        if level is not None and course is not None:
            payload["course"] = course

        duplicate = cls.base_queryset().filter(
            phone=payload.get("phone"), branch=branch, status__in=[
                LeadStatus.NEW, LeadStatus.CONTACTED, LeadStatus.TRIAL_SCHEDULED, LeadStatus.TRIAL_DONE
            ]
        ).first()
        if duplicate:
            raise BusinessRuleError(
                detail=f"Bu raqam bilan lead allaqachon mavjud (#{duplicate.id}).",
                code="duplicate_lead",
            )

        lead = Lead(**payload, created_by=actor)
        lead.full_clean(exclude=["created_by"])
        lead.save()
        cls._log_transition(lead, from_status="", to_status=lead.status, actor=actor,
                            comment="Lead yaratildi")
        return lead

    @classmethod
    def update_lead(cls, instance: Lead, data: Dict[str, Any], *, actor: Optional[User] = None) -> Lead:
        payload = cls.cleanup(data)
        new_status = payload.pop("status", None)
        for field, value in payload.items():
            setattr(instance, field, value)
        instance.full_clean(exclude=["created_by"])
        instance.save()
        if new_status and new_status != instance.status:
            instance = cls.change_status(instance, new_status, actor=actor)
        return instance

    # -- kanban ------------------------------------------------------------
    @classmethod
    def change_status(cls, instance: Lead, new_status: str, *, actor: Optional[User] = None,
                      comment: str = "") -> Lead:
        if new_status == instance.status:
            return instance
        allowed = cls.ALLOWED_TRANSITIONS.get(instance.status, [])
        if new_status not in allowed:
            raise BusinessRuleError(
                detail=(
                    f"'{instance.get_status_display()}' dan '{dict(LeadStatus.choices).get(new_status)}' "
                    f"ga o'tish mumkin emas."
                ),
                code="invalid_status_transition",
                errors={"allowed": allowed},
            )
        if new_status == LeadStatus.REJECTED:
            reason = comment or instance.rejected_reason
            if not reason:
                raise BusinessRuleError(
                    detail="Rad etish sababi ko'rsatilishi kerak.", code="rejection_reason_required"
                )
            instance.rejected_reason = reason
        if new_status == LeadStatus.CONVERTED and not instance.converted_student_id:
            raise BusinessRuleError(
                detail="Avval o'quvchiga aylantirish kerak.", code="convert_first"
            )
        if new_status == LeadStatus.TRIAL_SCHEDULED and not instance.trial_at:
            raise BusinessRuleError(
                detail="Sinov dars vaqtini ko'rsating.", code="trial_time_required"
            )

        previous = instance.status
        instance.status = new_status
        fields = ["status", "updated_at"]
        if new_status == LeadStatus.CONVERTED:
            instance.converted_at = timezone.now()
            fields.append("converted_at")
        if new_status == LeadStatus.REJECTED:
            fields.append("rejected_reason")
        instance.save(update_fields=fields)
        cls._log_transition(instance, from_status=previous, to_status=new_status,
                            actor=actor, comment=comment)
        return instance

    @classmethod
    def assign(cls, instance: Lead, manager: Optional[User], *, actor: Optional[User] = None) -> Lead:
        instance.assigned_to = manager
        instance.save(update_fields=["assigned_to", "updated_at"])
        cls._log_transition(instance, from_status=instance.status, to_status=instance.status,
                            actor=actor, comment=f"Mas'ul: {manager or 'boshqa'}")
        return instance

    @classmethod
    def reject(cls, instance: Lead, reason: str, *, actor: Optional[User] = None) -> Lead:
        return cls.change_status(instance, LeadStatus.REJECTED, actor=actor, comment=reason)

    # -- notes / calls -----------------------------------------------------
    @classmethod
    def add_note(cls, instance: Lead, text: str, *, actor: Optional[User] = None,
                 is_pinned: bool = False) -> LeadNote:
        if not text.strip():
            raise BusinessRuleError(detail="Izoh matni bo'sh bo'lmasligi kerak.", code="empty_note")
        return LeadNote.objects.create(lead=instance, author=actor, text=text, is_pinned=is_pinned)

    @classmethod
    def log_call(cls, instance: Lead, data: Dict[str, Any], *, actor: Optional[User] = None) -> LeadCall:
        payload = cls.cleanup(data)
        return LeadCall.objects.create(lead=instance, caller=actor, **payload)

    # -- follow-ups --------------------------------------------------------
    @classmethod
    def schedule_follow_up(cls, instance: Lead, due_at: datetime, *, note: str = "",
                           actor: Optional[User] = None, channel: str = "call") -> LeadFollowUp:
        if due_at is None:
            raise BusinessRuleError(detail="Sana va vaqt majburiy.", code="due_at_required")
        if timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at)
        follow_up = LeadFollowUp.objects.create(
            lead=instance,
            assigned_to=actor or instance.assigned_to,
            due_at=due_at,
            note=note,
            channel=channel,
        )
        instance.next_follow_up_at = due_at
        instance.save(update_fields=["next_follow_up_at", "updated_at"])
        cls._notify_follow_up(follow_up)
        return follow_up

    @classmethod
    def complete_follow_up(cls, follow_up: LeadFollowUp, *, status: str = FollowUpStatus.DONE,
                           comment: str = "") -> LeadFollowUp:
        if follow_up.status != FollowUpStatus.PENDING:
            raise BusinessRuleError(
                detail="Faqat kutilayotgan eslatma yopilishi mumkin.", code="follow_up_closed"
            )
        follow_up.status = status
        follow_up.completed_at = timezone.now()
        if comment:
            follow_up.note = f"{follow_up.note}\n[{status}] {comment}".strip()
        follow_up.save(update_fields=["status", "completed_at", "note", "updated_at"])
        cls._sync_next_follow_up(follow_up.lead)
        return follow_up

    @classmethod
    def due_follow_ups(cls, now: Optional[datetime] = None, branch_id: Optional[int] = None) -> List[LeadFollowUp]:
        now = now or timezone.now()
        queryset = LeadFollowUp.objects.filter(
            status=FollowUpStatus.PENDING, due_at__lte=now
        ).select_related("lead", "assigned_to")
        if branch_id:
            queryset = queryset.filter(lead__branch_id=branch_id)
        return list(queryset)

    # -- conversion --------------------------------------------------------
    @classmethod
    @transaction.atomic
    def convert_to_student(cls, instance: Lead, *, actor: Optional[User] = None,
                           group_id: Optional[int] = None, create_account: bool = True) -> Any:
        """Turns a lead into a real student (+ optional enrollment)."""
        from apps.students.models import Student
        from apps.students.services import EnrollmentService, StudentService

        if instance.is_converted:
            raise BusinessRuleError(
                detail="Bu lead allaqachon o'quvchiga aylantirilgan.", code="already_converted"
            )
        if instance.status == LeadStatus.REJECTED:
            raise BusinessRuleError(
                detail="Rad etilgan leadni o'quvchiga aylantirib bo'lmaydi.", code="lead_rejected"
            )

        name_parts = (instance.full_name or "").split(" ", 1)
        student = StudentService.create_student(
            {
                "branch": instance.branch,
                "first_name": instance.first_name or name_parts[0],
                "last_name": instance.last_name or (name_parts[1] if len(name_parts) > 1 else "-"),
                "phone": instance.phone,
                "email": instance.email,
                "telegram_id": instance.telegram_id,
                "birth_date": None,
                "source": instance.source,
                "notes": f"Lead #{instance.id} dan yaratilgan.",
                "create_portal_account": create_account,
                "portal_account": {
                    "username": f"student_{instance.phone}" if create_account else None,
                },
            },
            actor=actor,
        )
        instance.converted_student = student
        instance.status = LeadStatus.CONVERTED
        instance.converted_at = timezone.now()
        instance.save(update_fields=["converted_student", "status", "converted_at", "updated_at"])
        cls._log_transition(
            instance, from_status=instance.status, to_status=LeadStatus.CONVERTED,
            actor=actor, comment=f"O'quvchi #{student.pk} yaratildi",
        )

        if group_id:
            enrollment = EnrollmentService.enroll(
                {"student": student, "group_id": group_id}, actor=actor
            )
            student.refresh_from_db()
        return student

    # -- statistics --------------------------------------------------------
    @classmethod
    def pipeline_counts(cls, queryset=None) -> List[Dict[str, Any]]:
        queryset = queryset if queryset is not None else Lead.active.filter(is_active=True)
        counts = dict(queryset.values_list("status").annotate(total=Count("id")))
        return [
            {"status": status, "label": label, "count": counts.get(status, 0)}
            for status, label in LeadStatus.choices
        ]

    @classmethod
    def conversion_rate(cls, queryset=None) -> Dict[str, Any]:
        queryset = queryset if queryset is not None else Lead.active.filter(is_active=True)
        total = queryset.count()
        converted = queryset.filter(status=LeadStatus.CONVERTED).count()
        rejected = queryset.filter(status=LeadStatus.REJECTED).count()
        return {
            "total": total,
            "converted": converted,
            "rejected": rejected,
            "conversion_rate": round(converted / total * 100, 2) if total else 0.0,
        }

    # -- internals ---------------------------------------------------------
    @classmethod
    def _log_transition(cls, lead: Lead, *, from_status: str, to_status: str,
                        actor: Optional[User] = None, comment: str = "") -> LeadStatusHistory:
        return LeadStatusHistory.objects.create(
            lead=lead,
            from_status=from_status,
            to_status=to_status,
            comment=comment,
            changed_by=actor,
        )

    @classmethod
    def _sync_next_follow_up(cls, lead: Lead) -> None:
        upcoming = (
            LeadFollowUp.objects.filter(lead=lead, status=FollowUpStatus.PENDING)
            .order_by("due_at")
            .first()
        )
        lead.next_follow_up_at = upcoming.due_at if upcoming else None
        lead.save(update_fields=["next_follow_up_at", "updated_at"])

    @staticmethod
    def _notify_follow_up(follow_up: LeadFollowUp) -> None:
        """Schedules an SMS/call reminder via Celery (best effort)."""
        from apps.notifications.services import NotificationService

        try:
            NotificationService.create_for_lead_follow_up(follow_up)
        except Exception:  # pragma: no cover - notification must never break CRM
            pass
