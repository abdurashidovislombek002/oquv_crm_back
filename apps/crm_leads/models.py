"""Lead pipeline: statuses, sources, kanban history, notes, calls, follow-ups."""
from __future__ import annotations

from typing import Any, Dict, List

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from common.models import BaseModel
from common.querysets import RoleScopedQuerySet


class LeadStatus(models.TextChoices):
    NEW = "new", _("Yangi")
    CONTACTED = "contacted", _("Bog'lanildi")
    TRIAL_SCHEDULED = "trial_scheduled", _("Sinov darsga yozildi")
    TRIAL_DONE = "trial_done", _("Sinov darsda bo'ldi")
    CONVERTED = "converted", _("Mijozga aylantirildi")
    REJECTED = "rejected", _("Rad etdi")


class LeadSource(models.TextChoices):
    INSTAGRAM = "instagram", _("Instagram")
    TELEGRAM = "telegram", _("Telegram")
    REFERRAL = "referral", _("Tavsiya")
    WEBSITE = "website", _("Sayt")
    PHONE = "phone", _("Telefon")
    WALK_IN = "walk_in", _("Kelinibdi")
    OTHER = "other", _("Boshqa")


class LeadPriority(models.TextChoices):
    LOW = "low", _("Past")
    NORMAL = "normal", _("O'rtacha")
    HIGH = "high", _("Yuqori")
    HOT = "hot", _("Juda muhim")


class CallResult(models.TextChoices):
    ANSWERED = "answered", _("Javob berdi")
    NO_ANSWER = "no_answer", _("Javob bermadi")
    BUSY = "busy", _("Band")
    WRONG_NUMBER = "wrong_number", _("Noto'g'ri raqam")
    NOT_INTERESTED = "not_interested", _("Qiziqmaydi")
    CALL_BACK = "call_back", _("Qayta qo'ng'iroq qilish")


class CallDirection(models.TextChoices):
    INCOMING = "incoming", _("Kiruvchi")
    OUTGOING = "outgoing", _("Chiquvchi")


class FollowUpStatus(models.TextChoices):
    PENDING = "pending", _("Kutilmoqda")
    DONE = "done", _("Bajarildi")
    CANCELED = "canceled", _("Bekor qilindi")
    MISSED = "missed", _("Bajarilmadi")


class LeadQuerySet(RoleScopedQuerySet):
    def scope_default(self, user) -> "LeadQuerySet":
        return self.none()

    def scope_super_admin(self, user) -> "LeadQuerySet":
        return self

    def scope_branch_admin(self, user) -> "LeadQuerySet":
        return self.filter(branch_id=user.branch_id)

    def scope_manager(self, user) -> "LeadQuerySet":
        branch_leads = self.filter(branch_id=user.branch_id)
        if getattr(user, "role", None) == "manager":
            return branch_leads.filter(
                models.Q(assigned_to=user) | models.Q(assigned_to__isnull=True)
            )
        return branch_leads

    def scope_teacher(self, user) -> "LeadQuerySet":
        return self.none()

    def scope_student(self, user) -> "LeadQuerySet":
        return self.none()

    def scope_parent(self, user) -> "LeadQuerySet":
        return self.none()

    def with_related(self) -> "LeadQuerySet":
        return self.select_related(
            "branch", "course", "level", "assigned_to", "created_by", "converted_student"
        ).prefetch_related("notes", "calls", "follow_ups")

    def pipeline(self) -> "LeadQuerySet":
        """Open leads only (kanban board)."""
        return self.filter(status__in=[
            LeadStatus.NEW,
            LeadStatus.CONTACTED,
            LeadStatus.TRIAL_SCHEDULED,
            LeadStatus.TRIAL_DONE,
        ])


class Lead(BaseModel):
    """A potential customer."""

    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.CASCADE, related_name="leads", verbose_name=_("branch")
    )
    full_name = models.CharField(_("full name"), max_length=150)
    first_name = models.CharField(_("first name"), max_length=120, blank=True)
    last_name = models.CharField(_("last name"), max_length=120, blank=True)
    phone = models.CharField(_("phone"), max_length=32, db_index=True)
    email = models.EmailField(_("email"), blank=True)
    telegram_id = models.CharField(_("telegram id"), max_length=64, blank=True)
    age = models.PositiveSmallIntegerField(_("age"), null=True, blank=True)

    source = models.CharField(
        _("source"), max_length=20, choices=LeadSource.choices, default=LeadSource.OTHER, db_index=True
    )
    source_detail = models.CharField(_("source detail"), max_length=150, blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW,
        db_index=True,
    )
    priority = models.CharField(
        _("priority"), max_length=10, choices=LeadPriority.choices, default=LeadPriority.NORMAL
    )

    course = models.ForeignKey(
        "courses.Course", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="leads", verbose_name=_("interested course"),
    )
    level = models.ForeignKey(
        "courses.CourseLevel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="leads", verbose_name=_("interested level"),
    )
    preferred_days = models.CharField(_("preferred days"), max_length=150, blank=True)
    preferred_time = models.CharField(_("preferred time"), max_length=50, blank=True)

    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_leads",
        limit_choices_to={"role__in": ["manager", "branch_admin", "super_admin"]},
        verbose_name=_("responsible"),
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_leads",
        verbose_name=_("created by"),
    )

    estimated_deal_value = models.DecimalField(
        _("expected revenue"), max_digits=12, decimal_places=2, default=0
    )
    next_follow_up_at = models.DateTimeField(_("next follow-up"), null=True, blank=True, db_index=True)
    trial_at = models.DateTimeField(_("trial lesson"), null=True, blank=True)
    converted_at = models.DateTimeField(_("converted at"), null=True, blank=True)
    converted_student = models.ForeignKey(
        "students.Student", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="source_lead", verbose_name=_("converted student"),
    )
    rejected_reason = models.CharField(_("rejection reason"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        db_table = "crm_leads_lead"
        verbose_name = _("Lead")
        verbose_name_plural = _("Leadlar")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["branch", "status"], name="idx_lead_branch_status"),
            models.Index(fields=["status", "next_follow_up_at"], name="idx_lead_status_followup"),
        ]

    objects = models.Manager()
    active = LeadQuerySet.as_manager()

    def __str__(self) -> str:
        return f"{self.full_name} — {self.get_status_display()}"

    def save(self, *args, **kwargs) -> None:
        from common.utils import format_phone

        if self.phone:
            self.phone = format_phone(self.phone)
        if not self.full_name:
            parts = [self.first_name, self.last_name]
            self.full_name = " ".join(p for p in parts if p).strip() or self.phone
        super().save(*args, **kwargs)

    # -- computed ----------------------------------------------------------
    @property
    def is_converted(self) -> bool:
        return self.status == LeadStatus.CONVERTED

    @property
    def is_closed(self) -> bool:
        return self.status in (LeadStatus.CONVERTED, LeadStatus.REJECTED)

    @property
    def days_in_pipeline(self) -> int:
        return max((timezone.now() - self.created_at).days, 0)

    @property
    def is_overdue_follow_up(self) -> bool:
        return bool(self.next_follow_up_at and self.next_follow_up_at < timezone.now()
                    and not self.is_closed)

    @property
    def calls_count(self) -> int:
        cached = getattr(self, "calls_total", None)
        return cached if cached is not None else self.calls.count()


class LeadStatusHistory(models.Model):
    """Kanban transition log (``old_status -> new_status``)."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="status_history",
                             verbose_name=_("lead"))
    from_status = models.CharField(_("from status"), max_length=20, choices=LeadStatus.choices,
                                   blank=True)
    to_status = models.CharField(_("to status"), max_length=20, choices=LeadStatus.choices)
    comment = models.TextField(_("comment"), blank=True)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_status_changes",
        verbose_name=_("changed by"),
    )
    changed_at = models.DateTimeField(_("changed at"), default=timezone.now, db_index=True)

    class Meta:
        db_table = "crm_leads_lead_status_history"
        verbose_name = _("Holat tarixi")
        verbose_name_plural = _("Holat tarixi")
        ordering = ("-changed_at",)

    def __str__(self) -> str:
        return f"{self.lead_id}: {self.from_status} -> {self.to_status}"


class LeadNote(BaseModel):
    """Free-form note attached to a lead."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes", verbose_name=_("lead"))
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_notes",
        verbose_name=_("author"),
    )
    text = models.TextField(_("text"))
    is_pinned = models.BooleanField(_("pinned"), default=False)

    class Meta:
        db_table = "crm_leads_lead_note"
        verbose_name = _("Izoh")
        verbose_name_plural = _("Izohlar")
        ordering = ("-is_pinned", "-created_at")

    def __str__(self) -> str:
        return f"Izoh: {self.text[:40]}"


class LeadCall(BaseModel):
    """Call log."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="calls", verbose_name=_("lead"))
    caller = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_calls",
        verbose_name=_("caller"),
    )
    direction = models.CharField(_("direction"), max_length=10, choices=CallDirection.choices,
                                 default=CallDirection.OUTGOING)
    duration_seconds = models.PositiveIntegerField(_("duration (sec)"), default=0)
    result = models.CharField(_("result"), max_length=20, choices=CallResult.choices,
                              default=CallResult.ANSWERED)
    comment = models.TextField(_("comment"), blank=True)
    called_at = models.DateTimeField(_("called at"), default=timezone.now, db_index=True)

    class Meta:
        db_table = "crm_leads_lead_call"
        verbose_name = _("Qo'ng'iroq")
        verbose_name_plural = _("Qo'ng'iroqlar")
        ordering = ("-called_at",)

    def __str__(self) -> str:
        return f"{self.lead_id} — {self.get_result_display()}"


class LeadFollowUp(models.Model):
    """Scheduled reminder: "call this lead tomorrow at 10:00"."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="follow_ups",
                             verbose_name=_("lead"))
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_follow_ups",
        verbose_name=_("responsible"),
    )
    due_at = models.DateTimeField(_("due at"), db_index=True)
    status = models.CharField(
        _("status"), max_length=10, choices=FollowUpStatus.choices, default=FollowUpStatus.PENDING,
        db_index=True,
    )
    channel = models.CharField(_("channel"), max_length=20, default="call")
    note = models.TextField(_("note"), blank=True)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        db_table = "crm_leads_lead_follow_up"
        verbose_name = _("Eslatma (follow-up)")
        verbose_name_plural = _("Eslatmalar (follow-up)")
        ordering = ("status", "due_at")

    def __str__(self) -> str:
        return f"{self.lead_id} — {self.due_at:%Y-%m-%d %H:%M} ({self.get_status_display()})"

    @property
    def is_pending(self) -> bool:
        return self.status == FollowUpStatus.PENDING and self.due_at <= timezone.now()
