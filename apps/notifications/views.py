"""Views for notifications (log, templates, manual send)."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.pagination import CompactPagination
from common.permissions import IsManagerOrAbove
from common.views import BaseModelViewSet, BaseReadOnlyViewSet

from .filters import NotificationFilter, NotificationTemplateFilter
from .models import Notification, NotificationStatus, NotificationTemplate
from .serializers import (
    NotificationCreateSerializer,
    NotificationListSerializer,
    NotificationSerializer,
    NotificationTemplateRenderSerializer,
    NotificationTemplateSerializer,
)
from .services import NotificationService, NotificationTemplateService


class NotificationViewSet(BaseModelViewSet):
    """``/api/v1/notifications/``"""

    queryset = Notification.active.all()
    serializer_class = NotificationSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("subject", "body", "phone", "email")
    ordering_fields = ("created_at", "scheduled_at", "sent_at", "status")
    ordering = ("-created_at",)
    filterset_class = NotificationFilter
    pagination_class = CompactPagination
    serializer_class_map = {
        "list": NotificationListSerializer,
        "retrieve": NotificationSerializer,
        "create": NotificationCreateSerializer,
    }

    def get_queryset(self):
        queryset = super().get_queryset().select_related("branch", "recipient", "template")
        if self.request.query_params.get("pending") in ("1", "true", "yes"):
            return queryset.filter(
                status__in=[NotificationStatus.PENDING, NotificationStatus.QUEUED]
            )
        return queryset

    def get_permissions(self):
        if self.action in ("list", "retrieve", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def create(self, request, *args, **kwargs):
        serializer = NotificationCreateSerializer(
            data=request.data, context={"request": request, "send_now": False}
        )
        serializer.is_valid(raise_exception=True)
        notification = serializer.save()
        if str(request.data.get("send_now", "")).lower() in ("1", "true", "yes"):
            notification = NotificationService.send_now(notification.pk)
        return Response(NotificationSerializer(notification).data, status=201)

    @extend_schema(request=None, responses=NotificationSerializer, description="Hozir yuborish")
    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        notification = NotificationService.send_now(self.get_object().pk)
        return Response(NotificationSerializer(notification).data)

    @extend_schema(request=None, responses=NotificationSerializer, description="Bekor qilish")
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        notification = NotificationService.cancel(self.get_object())
        return Response(NotificationSerializer(notification).data)

    @extend_schema(request=None, responses=NotificationSerializer, description="Qayta urinish")
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        notification = NotificationService.retry(self.get_object())
        return Response(NotificationSerializer(notification).data)

    @extend_schema(responses=None, description="Statistika: kanal va holatlar kesimida")
    @action(detail=False, methods=["get"])
    def statistics(self, request):
        from django.db.models import Count
        from django.utils import timezone

        queryset = self.get_queryset()
        return Response(
            {
                "total": queryset.count(),
                "by_status": list(queryset.values("status").annotate(total=Count("id"))),
                "by_channel": list(queryset.values("channel").annotate(total=Count("id"))),
                "sent_today": queryset.filter(sent_at__date=timezone.localdate()).count(),
            }
        )


class NotificationTemplateViewSet(BaseModelViewSet):
    """``/api/v1/notification-templates/``"""

    queryset = NotificationTemplate.active.all()
    serializer_class = NotificationTemplateSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("key", "name", "body")
    ordering_fields = ("key", "channel", "created_at")
    ordering = ("channel", "key")
    filterset_class = NotificationTemplateFilter
    pagination_class = CompactPagination

    def get_permissions(self):
        if self.action in ("list", "retrieve", "render", "preview", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    @extend_schema(request=NotificationTemplateRenderSerializer, responses=None,
                   description="Shablonni kontekst bilan ko'rsatish")
    @action(detail=False, methods=["post"])
    def render(self, request):
        serializer = NotificationTemplateRenderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            NotificationTemplateService.render(
                serializer.validated_data["key"], serializer.validated_data.get("context", {})
            )
        )

    @extend_schema(responses=None, description="Tizimning standart shablonlari (JSON)")
    @action(detail=False, methods=["get"])
    def defaults(self, request):
        return Response(NotificationTemplateService.default_templates())

    @extend_schema(request=None, responses=NotificationTemplateSerializer(many=True))
    @action(detail=False, methods=["post"], url_path="install-defaults")
    def install_defaults(self, request):
        created = []
        for payload in NotificationTemplateService.default_templates():
            template, _ = NotificationTemplate.objects.update_or_create(
                key=payload["key"],
                defaults={
                    "name": payload["name"],
                    "channel": payload["channel"],
                    "subject": payload.get("subject", ""),
                    "body": payload["body"],
                    "variables": payload.get("variables", []),
                },
            )
            created.append(template)
        return Response(NotificationTemplateSerializer(created, many=True).data)
