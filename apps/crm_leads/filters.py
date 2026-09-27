"""Filters for the lead pipeline."""
from __future__ import annotations

import django_filters as filters
from django.db.models import Q

from common.filters import BaseFilterSet

from .models import (
    FollowUpStatus,
    Lead,
    LeadCall,
    LeadFollowUp,
    LeadNote,
    LeadSource,
    LeadStatus,
)


class LeadFilter(BaseFilterSet):
    full_name = filters.CharFilter(field_name="full_name", lookup_expr="icontains")
    phone = filters.CharFilter(field_name="phone", lookup_expr="icontains")
    branch = filters.NumberFilter(field_name="branch_id")
    status = filters.MultipleChoiceFilter(field_name="status", choices=LeadStatus.choices)
    source = filters.ChoiceFilter(field_name="source", choices=LeadSource.choices)
    course = filters.NumberFilter(field_name="course_id")
    level = filters.NumberFilter(field_name="level_id")
    assigned_to = filters.NumberFilter(field_name="assigned_to_id")
    has_trial = filters.BooleanFilter(field_name="trial_at", lookup_expr="isnull", exclude=True)
    overdue_follow_up = filters.BooleanFilter(method="filter_overdue_follow_up")
    created_from = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_to = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Lead
        fields = ("branch", "status", "source", "priority", "is_active")

    def filter_overdue_follow_up(self, queryset, name, value):
        from django.utils import timezone

        if value is None:
            return queryset
        closed = [LeadStatus.CONVERTED, LeadStatus.REJECTED]
        condition = Q(next_follow_up_at__lt=timezone.now())
        return queryset.filter(condition).exclude(status__in=closed) if value \
            else queryset.exclude(condition).exclude(status__in=closed)


class LeadNoteFilter(BaseFilterSet):
    lead = filters.NumberFilter(field_name="lead_id")

    class Meta:
        model = LeadNote
        fields = ("lead", "is_pinned")


class LeadCallFilter(BaseFilterSet):
    lead = filters.NumberFilter(field_name="lead_id")
    result = filters.CharFilter(field_name="result")

    class Meta:
        model = LeadCall
        fields = ("lead", "result", "direction")


class LeadFollowUpFilter(BaseFilterSet):
    lead = filters.NumberFilter(field_name="lead_id")
    assigned_to = filters.NumberFilter(field_name="assigned_to_id")
    status = filters.ChoiceFilter(field_name="status", choices=FollowUpStatus.choices)
    due_from = filters.DateTimeFilter(field_name="due_at", lookup_expr="gte")
    due_to = filters.DateTimeFilter(field_name="due_at", lookup_expr="lte")
    due = filters.BooleanFilter(method="filter_due")

    class Meta:
        model = LeadFollowUp
        fields = ("status",)

    def filter_due(self, queryset, name, value):
        from django.utils import timezone

        if value is None:
            return queryset
        condition = Q(due_at__lte=timezone.now())
        return queryset.filter(condition) if value else queryset.exclude(condition)
