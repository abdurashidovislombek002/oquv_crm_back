"""Serializers for the CRM lead pipeline."""
from __future__ import annotations

from typing import Any, Dict

from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import UserListSerializer
from apps.branches.models import Branch
from apps.groups.models import Group

from .models import (
    CallDirection,
    CallResult,
    FollowUpStatus,
    Lead,
    LeadCall,
    LeadFollowUp,
    LeadNote,
    LeadPriority,
    LeadSource,
    LeadStatus,
    LeadStatusHistory,
)


class LeadStatusHistorySerializer(serializers.ModelSerializer):
    changed_by = UserListSerializer(read_only=True)
    from_status_display = serializers.CharField(source="get_from_status_display", read_only=True)
    to_status_display = serializers.CharField(source="get_to_status_display", read_only=True)

    class Meta:
        model = LeadStatusHistory
        fields = ("id", "from_status", "from_status_display", "to_status", "to_status_display",
                  "comment", "changed_by", "changed_at")
        read_only_fields = fields


class LeadNoteSerializer(serializers.ModelSerializer):
    author = UserListSerializer(read_only=True)

    class Meta:
        model = LeadNote
        fields = ("id", "lead", "author", "text", "is_pinned", "created_at", "updated_at")
        read_only_fields = ("lead", "author", "created_at", "updated_at")


class LeadCallSerializer(serializers.ModelSerializer):
    caller = UserListSerializer(read_only=True)
    result_display = serializers.CharField(source="get_result_display", read_only=True)

    class Meta:
        model = LeadCall
        fields = ("id", "lead", "caller", "direction", "duration_seconds", "result",
                  "result_display", "comment", "called_at", "created_at")
        read_only_fields = ("lead", "caller", "created_at")


class LeadFollowUpSerializer(serializers.ModelSerializer):
    assigned_to = UserListSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lead_name = serializers.CharField(source="lead.full_name", read_only=True)
    lead_phone = serializers.CharField(source="lead.phone", read_only=True)

    class Meta:
        model = LeadFollowUp
        fields = ("id", "lead", "lead_name", "lead_phone", "assigned_to", "due_at", "status",
                  "status_display", "channel", "note", "completed_at", "created_at")
        read_only_fields = ("assigned_to", "completed_at", "created_at")


class LeadListSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True, default=None)
    level_name = serializers.CharField(source="level.name", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    assigned_to = UserListSerializer(read_only=True)
    days_in_pipeline = serializers.IntegerField(read_only=True)
    is_overdue_follow_up = serializers.BooleanField(read_only=True)

    class Meta:
        model = Lead
        fields = (
            "id", "full_name", "phone", "branch", "branch_name", "source", "source_display",
            "status", "status_display", "priority", "course", "course_name", "level",
            "level_name", "assigned_to", "estimated_deal_value", "next_follow_up_at",
            "trial_at", "days_in_pipeline", "is_overdue_follow_up", "is_active", "created_at",
        )


class LeadSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    assigned_to = UserListSerializer(read_only=True)
    created_by = UserListSerializer(read_only=True)
    converted_student = serializers.IntegerField(read_only=True, allow_null=True)
    status_history = LeadStatusHistorySerializer(many=True, read_only=True)
    notes_list = LeadNoteSerializer(source="notes", many=True, read_only=True)
    calls_list = LeadCallSerializer(source="calls", many=True, read_only=True)
    follow_ups = LeadFollowUpSerializer(many=True, read_only=True)
    days_in_pipeline = serializers.IntegerField(read_only=True)
    is_overdue_follow_up = serializers.BooleanField(read_only=True)

    class Meta:
        model = Lead
        fields = (
            "id", "branch", "branch_name", "full_name", "first_name", "last_name", "phone",
            "email", "telegram_id", "age", "source", "source_display", "source_detail",
            "status", "status_display", "priority", "course", "level", "preferred_days",
            "preferred_time", "assigned_to", "created_by", "estimated_deal_value",
            "next_follow_up_at", "trial_at", "converted_at", "converted_student",
            "rejected_reason", "notes", "status_history", "notes_list", "calls_list",
            "follow_ups", "days_in_pipeline", "is_overdue_follow_up", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = ("converted_student", "converted_at", "created_by")


class LeadWriteSerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all())
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role__in=["manager", "branch_admin", "super_admin"]),
        required=False, allow_null=True,
    )

    class Meta:
        model = Lead
        fields = (
            "id", "branch", "full_name", "first_name", "last_name", "phone", "email",
            "telegram_id", "age", "source", "source_detail", "status", "priority", "course",
            "level", "preferred_days", "preferred_time", "assigned_to",
            "estimated_deal_value", "next_follow_up_at", "trial_at", "notes", "is_active",
        )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        level = attrs.get("level")
        course = attrs.get("course") or (level.course if level else None)
        if level is not None and course is not None and level.course_id != course.id:
            raise serializers.ValidationError({"level": "Daraja boshqa kursga tegishli."})
        if course is not None:
            attrs["course"] = course
        return attrs


class LeadStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=LeadStatus.choices)
    comment = serializers.CharField(required=False, allow_blank=True)


class LeadNoteCreateSerializer(serializers.Serializer):
    text = serializers.CharField()
    is_pinned = serializers.BooleanField(required=False, default=False)


class LeadCallCreateSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(
        choices=CallDirection.choices, required=False, default=CallDirection.OUTGOING
    )
    duration_seconds = serializers.IntegerField(required=False, min_value=0, default=0)
    result = serializers.ChoiceField(choices=CallResult.choices, required=False,
                                     default=CallResult.ANSWERED)
    comment = serializers.CharField(required=False, allow_blank=True)
    called_at = serializers.DateTimeField(required=False)


class LeadFollowUpCreateSerializer(serializers.Serializer):
    due_at = serializers.DateTimeField()
    note = serializers.CharField(required=False, allow_blank=True)
    channel = serializers.CharField(required=False, default="call")


class LeadAssignSerializer(serializers.Serializer):
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )


class LeadConvertSerializer(serializers.Serializer):
    group = serializers.PrimaryKeyRelatedField(queryset=Group.objects.all(), required=False,
                                              allow_null=True)
    create_account = serializers.BooleanField(required=False, default=True)


class LeadBoardColumnSerializer(serializers.Serializer):
    status = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()
    leads = LeadListSerializer(many=True)
