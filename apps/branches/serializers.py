"""Serializers for branches and rooms."""
from __future__ import annotations

from rest_framework import serializers

from .models import Branch, Room


class RoomSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    room_type_display = serializers.CharField(source="get_room_type_display", read_only=True)

    class Meta:
        model = Room
        fields = (
            "id", "branch", "branch_name", "name", "code", "room_type", "room_type_display",
            "capacity", "floor", "has_projector", "has_whiteboard", "has_ac", "notes",
            "is_active", "created_at", "updated_at",
        )


class RoomListSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Room
        fields = ("id", "branch", "branch_name", "name", "code", "room_type", "capacity", "is_active")


class BranchSerializer(serializers.ModelSerializer):
    room_count = serializers.IntegerField(read_only=True)
    group_count = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Branch
        fields = (
            "id", "name", "code", "address", "district", "phone", "email", "director_name",
            "working_hours_from", "working_hours_to", "is_head_office", "description", "map_url",
            "room_count", "group_count", "student_count", "is_active", "created_at", "updated_at",
        )


class BranchListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ("id", "name", "code", "address", "phone", "is_head_office", "is_active")


class BranchStatisticsSerializer(serializers.Serializer):
    branches_count = serializers.IntegerField()
    rooms_count = serializers.IntegerField()
    groups_count = serializers.IntegerField()
    students_count = serializers.IntegerField()
    rooms_by_branch = serializers.ListField(child=serializers.DictField())
