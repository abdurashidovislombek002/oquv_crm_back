"""Filters for groups."""
from __future__ import annotations

import django_filters as filters
from django.db.models import Count, F, Q

from common.filters import BaseFilterSet

from .models import Group, GroupStatus


class GroupFilter(BaseFilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    code = filters.CharFilter(field_name="code", lookup_expr="iexact")
    branch = filters.NumberFilter(field_name="branch_id")
    course = filters.NumberFilter(field_name="course_id")
    level = filters.NumberFilter(field_name="level_id")
    room = filters.NumberFilter(field_name="room_id")
    teacher = filters.NumberFilter(field_name="teachers__id")
    status = filters.ChoiceFilter(field_name="status", choices=GroupStatus.choices)
    start_date_from = filters.DateFilter(field_name="start_date", lookup_expr="gte")
    start_date_to = filters.DateFilter(field_name="start_date", lookup_expr="lte")
    has_free_seats = filters.BooleanFilter(method="filter_has_free_seats")
    only_full = filters.BooleanFilter(method="filter_only_full")

    class Meta:
        model = Group
        fields = ("branch", "course", "level", "room", "status", "is_active")

    @staticmethod
    def _annotated():
        return Group.objects.annotate(
            students_total=Count(
                "enrollments",
                filter=Q(enrollments__is_active=True, enrollments__status="active"),
                distinct=True,
            )
        )

    def filter_has_free_seats(self, queryset, name, value):
        ids = list(
            self._annotated()
            .filter(students_total__lt=F("capacity"))
            .values_list("id", flat=True)
        )
        return queryset.filter(pk__in=ids) if value else queryset.exclude(pk__in=ids)

    def filter_only_full(self, queryset, name, value):
        ids = list(
            self._annotated()
            .filter(students_total__gte=F("capacity"))
            .values_list("id", flat=True)
        )
        return queryset.filter(pk__in=ids) if value else queryset.exclude(pk__in=ids)
