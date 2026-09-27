"""Filters for notifications."""
from __future__ import annotations

import django_filters as filters

from common.filters import BaseFilterSet

from .models import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationTemplate,
)


class NotificationFilter(BaseFilterSet):
    channel = filters.ChoiceFilter(field_name="channel", choices=NotificationChannel.choices)
    status = filters.MultipleChoiceFilter(field_name="status", choices=NotificationStatus.choices)
    branch = filters.NumberFilter(field_name="branch_id")
    recipient = filters.NumberFilter(field_name="recipient_id")
    student = filters.NumberFilter(field_name="student_id")
    lead = filters.NumberFilter(field_name="lead_id")
    scheduled_from = filters.DateTimeFilter(field_name="scheduled_at", lookup_expr="gte")
    scheduled_to = filters.DateTimeFilter(field_name="scheduled_at", lookup_expr="lte")

    class Meta:
        model = Notification
        fields = ("channel", "status", "is_active")


class NotificationTemplateFilter(BaseFilterSet):
    channel = filters.ChoiceFilter(field_name="channel", choices=NotificationChannel.choices)
    key = filters.CharFilter(field_name="key", lookup_expr="iexact")

    class Meta:
        model = NotificationTemplate
        fields = ("channel", "is_active")
