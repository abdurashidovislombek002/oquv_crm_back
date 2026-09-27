"""Serializers for groups and schedules."""
from __future__ import annotations

from typing import Any, Dict, List

from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import UserListSerializer
from apps.branches.models import Room
from apps.courses.serializers import CourseLevelListSerializer, CourseListSerializer

from .models import Group, GroupSchedule, GroupStatus


class GroupScheduleSerializer(serializers.ModelSerializer):
    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display", read_only=True
    )
    duration_minutes = serializers.IntegerField(read_only=True)
    time_range = serializers.CharField(read_only=True)

    class Meta:
        model = GroupSchedule
        fields = (
            "id", "group", "day_of_week", "day_of_week_display", "start_time", "end_time",
            "room", "duration_minutes", "time_range", "is_active_slot", "is_active",
        )


class GroupScheduleInputSerializer(serializers.Serializer):
    """Payload for ``PUT /groups/{id}/schedule/``."""

    day_of_week = serializers.IntegerField(min_value=1, max_value=7)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    room = serializers.PrimaryKeyRelatedField(
        queryset=Room.objects.all(), required=False, allow_null=True
    )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError(
                {"end_time": "Tugash vaqti boshlanishdan keyin bo'lishi kerak."}
            )
        return attrs


class GroupListSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)
    level_name = serializers.CharField(source="level.name", read_only=True)
    teacher_names = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    students_count = serializers.IntegerField(read_only=True, required=False)
    filled_seats = serializers.IntegerField(read_only=True)
    free_seats = serializers.IntegerField(read_only=True)
    fill_rate = serializers.FloatField(read_only=True)
    schedule_summary = serializers.CharField(read_only=True)

    class Meta:
        model = Group
        fields = (
            "id", "name", "code", "branch", "branch_name", "course", "course_name",
            "level", "level_name", "room", "status", "status_display", "capacity",
            "students_count", "filled_seats", "free_seats", "fill_rate", "start_date",
            "end_date", "start_time", "end_time", "teacher_names", "schedule_summary",
            "is_active", "created_at",
        )


class GroupDetailSerializer(GroupListSerializer):
    teachers = UserListSerializer(many=True, read_only=True)
    head_teacher = UserListSerializer(read_only=True)
    course = CourseListSerializer(read_only=True)
    level = CourseLevelListSerializer(read_only=True)
    schedule = GroupScheduleSerializer(many=True, read_only=True)
    effective_fee = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    can_start = serializers.BooleanField(read_only=True)

    class Meta(GroupListSerializer.Meta):
        fields = GroupListSerializer.Meta.fields + (
            "teachers", "head_teacher", "schedule", "monthly_fee", "effective_fee",
            "min_students", "description", "color", "created_by", "can_start", "updated_at",
        )


class GroupWriteSerializer(serializers.ModelSerializer):
    """Create/update payload (nested teachers + schedule accepted)."""

    teachers = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role="teacher").select_related("branch"),
        many=True, required=False, allow_null=True,
    )
    schedule = GroupScheduleInputSerializer(many=True, required=False, write_only=True)

    class Meta:
        model = Group
        fields = (
            "id", "name", "code", "branch", "course", "level", "room", "teachers",
            "head_teacher", "status", "capacity", "min_students", "start_date", "end_date",
            "start_time", "end_time", "monthly_fee", "description", "color", "schedule",
            "is_active",
        )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        level = attrs.get("level") or getattr(self.instance, "level", None)
        course = attrs.get("course") or getattr(self.instance, "course", None)
        if level is not None and course is not None and level.course_id != course.id:
            raise serializers.ValidationError({"level": "Daraja boshqa kursga tegishli."})
        room = attrs.get("room")
        branch = attrs.get("branch") or getattr(self.instance, "branch", None)
        if room is not None and branch is not None and room.branch_id != branch.id:
            raise serializers.ValidationError({"room": "Xona boshqa filialga tegishli."})
        return attrs

    def create(self, validated_data: Dict[str, Any]) -> Group:
        from .services import GroupService

        actor = getattr(self.context.get("request"), "user", None)
        return GroupService.create_group(validated_data, actor=actor)

    def update(self, instance: Group, validated_data: Dict[str, Any]) -> Group:
        from .services import GroupService

        actor = getattr(self.context.get("request"), "user", None)
        return GroupService.update_group(instance, validated_data, actor=actor)
