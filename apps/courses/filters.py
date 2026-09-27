"""Filters for the course catalog."""
from __future__ import annotations

import django_filters as filters

from common.filters import BaseFilterSet

from .models import Course, CourseLevel


class CourseFilter(BaseFilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    category = filters.CharFilter(field_name="category", lookup_expr="iexact")
    min_price = filters.NumberFilter(field_name="base_price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="base_price", lookup_expr="lte")
    is_featured = filters.BooleanFilter(field_name="is_featured")

    class Meta:
        model = Course
        fields = ("category", "is_active", "is_featured")


class CourseLevelFilter(BaseFilterSet):
    course = filters.NumberFilter(field_name="course_id")
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = CourseLevel
        fields = ("course", "is_active")
