"""Filters for lessons/attendance."""
from __future__ import annotations

import django_filters as filters

from common.filters import BaseFilterSet

from .models import AttendanceRecord, AttendanceStatus, Lesson, LessonStatus


class LessonFilter(BaseFilterSet):
    group = filters.NumberFilter(field_name="group_id")
    branch = filters.NumberFilter(field_name="branch_id")
    teacher = filters.NumberFilter(field_name="teacher_id")
    course = filters.NumberFilter(field_name="group__course_id")
    status = filters.ChoiceFilter(field_name="status", choices=LessonStatus.choices)
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")
    unmarked = filters.BooleanFilter(method="filter_unmarked")

    class Meta:
        model = Lesson
        fields = ("group", "branch", "status", "is_active")

    def filter_unmarked(self, queryset, name, value):
        if value is None:
            return queryset
        from django.db.models import Exists, OuterRef

        from .models import AttendanceRecord as Record

        marked = Record.objects.filter(lesson=OuterRef("pk"), is_active=True)
        return queryset.filter(marked) if value else queryset.filter(~Exists(marked))


class AttendanceRecordFilter(BaseFilterSet):
    lesson = filters.NumberFilter(field_name="lesson_id")
    student = filters.NumberFilter(field_name="student_id")
    group = filters.NumberFilter(field_name="lesson__group_id")
    status = filters.ChoiceFilter(field_name="status", choices=AttendanceStatus.choices)
    date_from = filters.DateFilter(field_name="lesson__date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="lesson__date", lookup_expr="lte")

    class Meta:
        model = AttendanceRecord
        fields = ("lesson", "student", "status", "is_active")
