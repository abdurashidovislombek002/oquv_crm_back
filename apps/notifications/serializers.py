"""Serializers for notifications."""
from __future__ import annotations

from typing import Any, Dict, List

from rest_framework import serializers

from apps.accounts.serializers import UserListSerializer

from .models import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationTemplate,
)


class NotificationTemplateSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)

    class Meta:
        model = NotificationTemplate
        fields = (
            "id", "key", "name", "channel", "channel_display", "subject", "body", "variables",
            "description", "is_active", "created_at", "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class NotificationListSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    target_address = serializers.CharField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id", "channel", "channel_display", "subject", "status", "status_display",
            "scheduled_at", "sent_at", "attempts", "target_address", "created_at",
        )


class NotificationSerializer(serializers.ModelSerializer):
    recipient = UserListSerializer(read_only=True)
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    target_address = serializers.CharField(read_only=True)
    is_sent = serializers.BooleanField(read_only=True)
    is_pending = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id", "branch", "channel", "channel_display", "recipient", "student", "lead",
            "template", "phone", "email", "telegram_id", "subject", "body", "status",
            "status_display", "priority", "scheduled_at", "sent_at", "attempts",
            "error_message", "target_address", "is_sent", "is_pending", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = ("sent_at", "attempts", "error_message", "is_sent", "is_pending")


class NotificationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            "id", "branch", "channel", "recipient", "student", "template", "phone", "email",
            "telegram_id", "subject", "body", "priority", "scheduled_at",
        )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        if not attrs.get("body"):
            raise serializers.ValidationError({"body": "Xabar matni majburiy."})
        channel = attrs.get("channel")
        if channel == NotificationChannel.EMAIL and not attrs.get("email"):
            raise serializers.ValidationError({"email": "Email kanal uchun manzil majburiy."})
        return attrs

    def create(self, validated_data: Dict[str, Any]) -> Notification:
        from .services import NotificationService

        actor = getattr(self.context.get("request"), "user", None)
        send_now = self.context.get("send_now", False)
        return NotificationService.create(validated_data, actor=actor, send_now=send_now)


class NotificationTemplateRenderSerializer(serializers.Serializer):
    key = serializers.CharField()
    context = serializers.DictField(default=dict, required=False)

    def create(self, validated_data):  # pragma: no cover - not used
        raise NotImplementedError


class SendNowSerializer(serializers.Serializer):
    send_now = serializers.BooleanField(default=True)
