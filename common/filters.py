"""Reusable ``django-filter`` FilterSets."""
from __future__ import annotations

import django_filters as filters


class BaseFilterSet(filters.FilterSet):
    """Adds universal date-range filters to every list endpoint."""

    created_after = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")
    updated_after = filters.IsoDateTimeFilter(field_name="updated_at", lookup_expr="gte")
    updated_before = filters.IsoDateTimeFilter(field_name="updated_at", lookup_expr="lte")
    is_active = filters.BooleanFilter(field_name="is_active")

    class Meta:
        abstract = True


class DateRangeFilterSet(BaseFilterSet):
    """For models that expose a business ``date`` field (lessons, payments...)."""

    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")


class BranchFilterMixin:
    """Adds ``?branch_id=`` / ``?branch=`` filters (superadmin only)."""

    branch = filters.NumberFilter(field_name="branch_id")


class BooleanQueryFilter(filters.BooleanFilter):
    """Allows ``?flag=true``/``?flag=1`` style booleans."""
