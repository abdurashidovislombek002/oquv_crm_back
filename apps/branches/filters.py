"""Filters for branches/rooms."""
from __future__ import annotations

import django_filters as filters

from common.filters import BaseFilterSet

from .models import Branch, Room, RoomType


class BranchFilter(BaseFilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    code = filters.CharFilter(field_name="code", lookup_expr="iexact")
    district = filters.CharFilter(field_name="district", lookup_expr="icontains")
    is_head_office = filters.BooleanFilter(field_name="is_head_office")

    class Meta:
        model = Branch
        fields = ("name", "code", "district", "is_head_office", "is_active")


class RoomFilter(BaseFilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    branch = filters.NumberFilter(field_name="branch_id")
    room_type = filters.ChoiceFilter(field_name="room_type", choices=RoomType.choices)
    min_capacity = filters.NumberFilter(field_name="capacity", lookup_expr="gte")

    class Meta:
        model = Room
        fields = ("branch", "room_type", "is_active")
