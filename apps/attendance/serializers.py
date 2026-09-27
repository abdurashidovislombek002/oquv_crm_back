"""Serializers for lessons and attendance."""
from __future__ import annotations

from typing import Any, Dict, List

from rest_framework import serializers

from apps.accounts.serializers import UserListSerializer

from .models import AttendanceRecord, AttendanceStatus, Lesson, LessonStatus


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    marked_by = UserListSerializer(read_only=True)
    is_present = serializers.BooleanField(read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = (
            "id", "lesson", "student", "student_name", "status", "status_display",
            "minutes_late", "note", "marked_at", "marked_by", "is_present", "is_active",
        )
        read_only_fields = ("marked_at", "marked_by", "is_present")


class BulkAttendanceItemSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=AttendanceStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True)
    minutes_late = serializers.IntegerField(required=False, min_value=0, default=0)


class BulkAttendanceSerializer(serializers.Serializer):
    records = BulkAttendanceItemSerializer(many=True)


class LessonListSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="group.name", read_only=True)
    course_name = serializers.CharField(source="group.course.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    teacher = UserListSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    students_count = serializers.IntegerField(read_only=True)
    attendance_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = Lesson
        fields = (
            "id", "group", "group_name", "course_name", "branch", "branch_name", "date",
            "start_time", "end_time", "room", "teacher", "status", "status_display",
            "topic", "students_count", "attendance_rate", "is_active",
        )


class LessonSerializer(LessonListSerializer):
    records = AttendanceRecordSerializer(many=True, read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    created_by = UserListSerializer(read_only=True)

    class Meta(LessonListSerializer.Meta):
        fields = LessonListSerializer.Meta.fields + (
            "homework", "is_generated", "duration_minutes", "records", "created_by",
            "created_at", "updated_at",
        )


class LessonWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = (
            "id", "group", "date", "start_time", "end_time", "room", "teacher", "topic",
            "homework", "status", "is_active",
        )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        start = attrs.get("start_time") or getattr(self.instance, "start_time", None)
        end = attrs.get("end_time") or getattr(self.instance, "end_time", None)
        if start and end and start >= end:
            raise serializers.ValidationError(
                {"end_time": "Tugash vaqti boshlanishdan keyin bo'lishi kerak."}
            )
        return attrs


class GenerateScheduleSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()


class AttendanceReportSerializer(serializers.Serializer):
    total_lessons = serializers.IntegerField(required=False)
    total_records = serializers.IntegerField(required=False)
    present = serializers.IntegerField()
    absent = serializers.IntegerField()
    late = serializers.IntegerField()
    excused = serializers.IntegerField()
    online = serializers.IntegerField(required=False)
    attendance_rate = serializers.FloatField()
    students = serializers.ListField(child=serializers.DictField(), required=False)
    lessons_count = serializers.IntegerField(required=False)


class DailyAttendanceReportSerializer(AttendanceReportSerializer):
    date = serializers.DateField()
    lessons_without_marks = serializers.IntegerField()
