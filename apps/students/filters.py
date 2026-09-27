"""Filters for students/enrollments."""
from __future__ import annotations

import django_filters as filters

from common.filters import BaseFilterSet

from .models import Enrollment, EnrollmentStatus, Student, StudentStatus


class StudentFilter(BaseFilterSet):
    first_name = filters.CharFilter(field_name="first_name", lookup_expr="icontains")
    last_name = filters.CharFilter(field_name="last_name", lookup_expr="icontains")
    phone = filters.CharFilter(field_name="phone", lookup_expr="icontains")
    telegram_id = filters.CharFilter(field_name="telegram_id", lookup_expr="icontains")
    branch = filters.NumberFilter(field_name="branch_id")
    status = filters.ChoiceFilter(field_name="status", choices=StudentStatus.choices)
    group = filters.NumberFilter(field_name="enrollments__group_id")
    course = filters.NumberFilter(field_name="enrollments__group__course_id")
    teacher = filters.NumberFilter(field_name="enrollments__group__teachers__id")
    parent = filters.NumberFilter(field_name="parents__id")
    without_group = filters.BooleanFilter(method="filter_without_group")

    class Meta:
        model = Student
        fields = ("branch", "status", "is_active")

    def filter_without_group(self, queryset, name, value):
        if value is None:
            return queryset
        from django.db.models import Exists, OuterRef

        enrollment = Enrollment.objects.filter(
            student=OuterRef("pk"), is_active=True, status=EnrollmentStatus.ACTIVE
        )
        return queryset.filter(Exists(enrollment)).distinct() if not value \
            else queryset.filter(~Exists(enrollment))


class EnrollmentFilter(BaseFilterSet):
    student = filters.NumberFilter(field_name="student_id")
    group = filters.NumberFilter(field_name="group_id")
    branch = filters.NumberFilter(field_name="group__branch_id")
    course = filters.NumberFilter(field_name="group__course_id")
    status = filters.ChoiceFilter(field_name="status", choices=EnrollmentStatus.choices)
    start_date_from = filters.DateFilter(field_name="start_date", lookup_expr="gte")
    start_date_to = filters.DateFilter(field_name="start_date", lookup_expr="lte")

    class Meta:
        model = Enrollment
        fields = ("status", "is_active")
