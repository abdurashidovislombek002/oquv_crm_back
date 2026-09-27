"""Serializers for the course catalog."""
from __future__ import annotations

from rest_framework import serializers

from .models import Course, CourseLevel


class CourseLevelSerializer(serializers.ModelSerializer):
    groups_count = serializers.IntegerField(read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)

    class Meta:
        model = CourseLevel
        fields = (
            "id", "course", "course_name", "name", "slug", "code", "description", "price",
            "duration_months", "min_students_to_open", "max_students_per_group", "ordering",
            "groups_count", "is_active", "created_at", "updated_at",
        )


class CourseLevelListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseLevel
        fields = ("id", "course", "name", "code", "price", "duration_months", "ordering", "is_active")


class CourseSerializer(serializers.ModelSerializer):
    levels = CourseLevelSerializer(many=True, read_only=True)
    levels_count = serializers.IntegerField(read_only=True)
    groups_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Course
        fields = (
            "id", "name", "slug", "category", "description", "goals", "duration_months",
            "lessons_per_week", "lesson_duration_minutes", "base_price", "min_age", "max_age",
            "cover_url", "is_featured", "ordering", "levels", "levels_count", "groups_count",
            "is_active", "created_at", "updated_at",
        )


class CourseListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = (
            "id", "name", "slug", "category", "base_price", "duration_months",
            "lessons_per_week", "cover_url", "is_featured", "ordering", "is_active",
        )


class CourseCatalogItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    category = serializers.CharField(allow_blank=True)
    base_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    duration_months = serializers.IntegerField()
    levels_count = serializers.IntegerField()
    groups_count = serializers.IntegerField()
