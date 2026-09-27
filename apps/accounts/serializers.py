"""Serializers for accounts."""
from __future__ import annotations

from typing import Any, Dict

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.branches.models import Branch
from common.constants import format_phone
from common.permissions import has_role

from .constants import MANAGEMENT_ROLES, Role
from .models import User, UserActivity


class BranchMiniSerializer(serializers.Serializer):
    """Lightweight branch representation embedded in user payloads."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    code = serializers.CharField(read_only=True)


class UserListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    initials = serializers.CharField(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    branch = BranchMiniSerializer(read_only=True)
    branch_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "full_name", "initials", "first_name", "last_name",
            "role", "role_display", "branch", "branch_name", "phone", "telegram_id",
            "avatar_url", "is_active", "date_joined", "last_login",
        )


class UserDetailSerializer(UserListSerializer):
    class Meta(UserListSerializer.Meta):
        fields = UserListSerializer.Meta.fields + (
            "middle_name", "birth_date", "address", "notes", "is_staff", "is_superuser",
            "created_at", "updated_at",
        )
        read_only_fields = fields


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, min_length=8, trim_whitespace=False)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "password", "first_name", "last_name", "middle_name",
            "role", "branch", "phone", "telegram_id", "birth_date", "address", "avatar_url", "notes",
        )

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate_phone(self, value: str) -> str:
        return format_phone(value)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        role = attrs.get("role") or Role.STUDENT
        if role in (Role.BRANCH_ADMIN, Role.MANAGER, Role.TEACHER) and not attrs.get("branch"):
            raise serializers.ValidationError(
                {"branch": "Bu rol uchun filial tanlash majburiy."}
            )
        return attrs

    def create(self, validated_data: Dict[str, Any]) -> User:
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class UserUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=False, min_length=8, trim_whitespace=False
    )

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "first_name", "last_name", "middle_name", "role",
            "branch", "phone", "telegram_id", "birth_date", "address", "avatar_url",
            "notes", "is_active", "password",
        )

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def update(self, instance: User, validated_data: Dict[str, Any]) -> User:
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class MeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    initials = serializers.CharField(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    branch = BranchMiniSerializer(read_only=True)

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "full_name", "initials", "first_name", "last_name",
            "middle_name", "role", "role_display", "branch", "phone", "telegram_id",
            "avatar_url", "birth_date", "address", "is_active", "date_joined", "last_login",
        )
        read_only_fields = ("id", "username", "email", "role", "role_display", "branch")


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, required=True, min_length=8, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, required=True, trim_whitespace=False)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Parollar mos kelmadi."}
            )
        try:
            validate_password(attrs["new_password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return attrs


class SetRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True
    )


class UserActivitySerializer(serializers.ModelSerializer):
    user = UserListSerializer(read_only=True)
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = UserActivity
        fields = ("id", "user", "action", "action_display", "ip_address", "user_agent", "created_at")
        read_only_fields = fields


class TokenObtainPairCustomSerializer(TokenObtainPairSerializer):
    """Adds the user profile to the login/refresh response."""

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        data = super().validate(attrs)
        data["user"] = UserDetailSerializer(self.user).data
        return data
