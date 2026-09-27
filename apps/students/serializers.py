"""Serializers for students and enrollments."""
from __future__ import annotations

from typing import Any, Dict

from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import UserListSerializer

from .models import Enrollment, EnrollmentStatus, Student, StudentStatus


class EnrollmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True)
    course_name = serializers.CharField(source="group.course.name", read_only=True)
    base_fee = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_fee = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_discount_percent = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Enrollment
        fields = (
            "id", "student", "student_name", "group", "group_name", "course_name", "status",
            "status_display", "start_date", "end_date", "monthly_fee", "base_fee", "final_fee",
            "discount_percent", "total_discount_percent", "discount", "is_paid_current_month",
            "notes", "duration_days", "is_active", "created_at", "updated_at",
        )
        read_only_fields = ("duration_days", "is_active", "created_at", "updated_at")


class EnrollmentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enrollment
        fields = (
            "id", "student", "group", "status", "start_date", "end_date", "monthly_fee",
            "discount_percent", "discount", "notes", "is_active",
        )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        student = attrs.get("student") or getattr(self.instance, "student", None)
        group = attrs.get("group") or getattr(self.instance, "group", None)
        if student and group and student.branch_id != group.branch_id:
            raise serializers.ValidationError(
                {"group": "O'quvchi va guruh turli filiallarga tegishli."}
            )
        return attrs


class StudentListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    groups_count = serializers.IntegerField(read_only=True, required=False)
    primary_group = serializers.CharField(source="primary_group.name", read_only=True, default=None)

    class Meta:
        model = Student
        fields = (
            "id", "full_name", "first_name", "last_name", "branch", "branch_name", "phone",
            "status", "status_display", "age", "birth_date", "groups_count", "primary_group",
            "start_date", "is_active",
        )


class StudentSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    parents = UserListSerializer(many=True, read_only=True)
    portal_account = UserListSerializer(source="user", read_only=True)
    enrollments = EnrollmentSerializer(many=True, read_only=True)
    groups_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Student
        fields = (
            "id", "user", "portal_account", "branch", "branch_name", "first_name", "last_name",
            "middle_name", "full_name", "birth_date", "age", "gender", "phone", "email",
            "telegram_id", "address", "school", "photo_url", "status", "status_display",
            "parents", "start_date", "finish_date", "discount_percent", "source", "notes",
            "enrollments", "groups_count", "is_active", "created_at", "updated_at",
        )


class StudentWriteSerializer(serializers.ModelSerializer):
    parents = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role="parent"), many=True, required=False
    )
    create_portal_account = serializers.BooleanField(write_only=True, required=False, default=False)
    portal_username = serializers.CharField(write_only=True, required=False, allow_blank=True)
    portal_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False
    )

    class Meta:
        model = Student
        fields = (
            "id", "branch", "first_name", "last_name", "middle_name", "birth_date", "gender",
            "phone", "email", "telegram_id", "address", "school", "photo_url", "status",
            "parents", "start_date", "finish_date", "discount_percent", "source", "notes",
            "is_active", "create_portal_account", "portal_username", "portal_password",
        )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        discount = attrs.get("discount_percent")
        if discount is not None and not (0 <= discount <= 100):
            raise serializers.ValidationError(
                {"discount_percent": "Chegirma 0-100 orasida bo'lishi kerak."}
            )
        return attrs

    def create(self, validated_data: Dict[str, Any]) -> Student:
        from .services import StudentService

        portal_username = validated_data.pop("portal_username", "")
        portal_password = validated_data.pop("portal_password", "")
        create_portal = validated_data.pop("create_portal_account", False)
        portal = {}
        if create_portal or portal_username:
            portal = {
                "username": portal_username or None,
                "password": portal_password or None,
                "email": validated_data.get("email") or None,
            }
        actor = getattr(self.context.get("request"), "user", None)
        return StudentService.create_student(
            {**validated_data, "portal_account": portal, "create_portal_account": bool(portal)},
            actor=actor,
        )

    def update(self, instance: Student, validated_data: Dict[str, Any]) -> Student:
        from .services import StudentService

        validated_data.pop("portal_username", None)
        validated_data.pop("portal_password", None)
        create_portal = validated_data.pop("create_portal_account", False)
        actor = getattr(self.context.get("request"), "user", None)
        if create_portal and not instance.user_id:
            validated_data["portal_account"] = {
                "username": validated_data.get("portal_username"),
                "email": instance.email or None,
            }
        return StudentService.update_student(instance, validated_data, actor=actor)


class StudentStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=StudentStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class EnrollmentMoveSerializer(serializers.Serializer):
    group = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True)
