"""Views for the lead pipeline (kanban board, notes, calls, follow-ups)."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.pagination import CompactPagination
from common.permissions import CanManageLead, IsManagerOrAbove
from common.views import BaseModelViewSet, BaseReadOnlyViewSet

from .filters import LeadCallFilter, LeadFilter, LeadFollowUpFilter, LeadNoteFilter
from .models import (
    Lead,
    LeadCall,
    LeadFollowUp,
    LeadNote,
    LeadStatus,
    LeadStatusHistory,
)
from .serializers import (
    LeadAssignSerializer,
    LeadCallCreateSerializer,
    LeadCallSerializer,
    LeadConvertSerializer,
    LeadFollowUpCreateSerializer,
    LeadFollowUpSerializer,
    LeadListSerializer,
    LeadNoteCreateSerializer,
    LeadNoteSerializer,
    LeadSerializer,
    LeadStatusChangeSerializer,
    LeadStatusHistorySerializer,
    LeadWriteSerializer,
)
from .services import LeadService


class LeadViewSet(BaseModelViewSet):
    """``/api/v1/leads/``"""

    queryset = Lead.active.all()
    serializer_class = LeadSerializer
    permission_classes = (CanManageLead,)
    search_fields = ("full_name", "phone", "email", "telegram_id", "notes")
    ordering_fields = ("created_at", "next_follow_up_at", "status", "estimated_deal_value")
    ordering = ("-created_at",)
    filterset_class = LeadFilter
    pagination_class = CompactPagination
    serializer_class_map = {
        "list": LeadListSerializer,
        "retrieve": LeadSerializer,
        "create": LeadWriteSerializer,
        "update": LeadWriteSerializer,
        "partial_update": LeadWriteSerializer,
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in ("retrieve",):
            return queryset.with_related()
        return queryset

    def perform_create(self, serializer) -> None:
        serializer.instance = LeadService.create_lead(
            serializer.validated_data, actor=self.request.user
        )

    def perform_update(self, serializer) -> None:
        LeadService.update_lead(
            serializer.instance, serializer.validated_data, actor=self.request.user
        )

    def get_permissions(self):
        if self.action in ("board", "pipeline_counts", "options"):
            return [IsAuthenticated()]
        return [CanManageLead()]

    # -- kanban board ------------------------------------------------------
    @extend_schema(
        responses=None,
        description="Kanban doskasi: statuslar bo'yicha guruhlangan leadlar",
    )
    @action(detail=False, methods=["get"], url_path="board")
    def board(self, request):
        queryset = self.get_queryset().filter(is_active=True)
        board = []
        for status, label in LeadStatus.choices:
            leads = list(queryset.filter(status=status).order_by("-created_at")[:100])
            board.append(
                {"status": status, "label": label, "count": len(leads),
                 "leads": LeadListSerializer(leads, many=True).data}
            )
        return Response(board)

    @extend_schema(responses=None, description="Pipeline bo'yicha leadlar soni")
    @action(detail=False, methods=["get"], url_path="pipeline-counts")
    def pipeline_counts(self, request):
        return Response(LeadService.pipeline_counts(self.get_queryset().filter(is_active=True)))

    @extend_schema(request=LeadStatusChangeSerializer, responses=LeadSerializer)
    @action(detail=True, methods=["post"], url_path="change-status")
    def change_status(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = LeadService.change_status(
            lead,
            serializer.validated_data["status"],
            actor=request.user,
            comment=serializer.validated_data.get("comment", ""),
        )
        return Response(LeadSerializer(lead).data)

    @extend_schema(request=LeadAssignSerializer, responses=LeadSerializer)
    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = LeadService.assign(lead, serializer.validated_data.get("assigned_to"),
                                  actor=request.user)
        return Response(LeadSerializer(lead).data)

    @extend_schema(request=LeadNoteCreateSerializer, responses=LeadNoteSerializer)
    @action(detail=True, methods=["post"], url_path="add-note")
    def add_note(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = LeadService.add_note(
            lead,
            serializer.validated_data["text"],
            actor=request.user,
            is_pinned=serializer.validated_data.get("is_pinned", False),
        )
        return Response(LeadNoteSerializer(note).data, status=201)

    @extend_schema(request=LeadCallCreateSerializer, responses=LeadCallSerializer)
    @action(detail=True, methods=["post"], url_path="log-call")
    def log_call(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadCallCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        call = LeadService.log_call(lead, serializer.validated_data, actor=request.user)
        return Response(LeadCallSerializer(call).data, status=201)

    @extend_schema(
        request=LeadFollowUpCreateSerializer,
        responses=LeadFollowUpSerializer,
        description="Eslatma (follow-up) rejalashtirish — Celery orqali xabarnoma yuboriladi",
    )
    @action(detail=True, methods=["post"], url_path="follow-up")
    def follow_up(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadFollowUpCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        follow_up = LeadService.schedule_follow_up(
            lead,
            serializer.validated_data["due_at"],
            note=serializer.validated_data.get("note", ""),
            actor=request.user,
            channel=serializer.validated_data.get("channel", "call"),
        )
        return Response(LeadFollowUpSerializer(follow_up).data, status=201)

    @extend_schema(request=LeadConvertSerializer, responses=None,
                   description="Leadni o'quvchiga aylantirish")
    @action(detail=True, methods=["post"], url_path="convert")
    def convert(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadConvertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = serializer.validated_data.get("group")
        student = LeadService.convert_to_student(
            lead,
            actor=request.user,
            group_id=group.id if group else None,
            create_account=serializer.validated_data.get("create_account", True),
        )
        from apps.students.serializers import StudentSerializer

        return Response(StudentSerializer(student).data, status=201)

    @extend_schema(responses=LeadStatusHistorySerializer(many=True))
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        lead = self.get_object()
        return Response(
            LeadStatusHistorySerializer(lead.status_history.all(), many=True).data
        )


class LeadStatusHistoryViewSet(BaseReadOnlyViewSet):
    """``/api/v1/lead-status-history/``"""

    queryset = LeadStatusHistory.objects.select_related("lead", "changed_by").all()
    serializer_class = LeadStatusHistorySerializer
    permission_classes = (CanManageLead,)
    search_fields = ("lead__full_name", "lead__phone", "comment")
    ordering_fields = ("changed_at",)
    ordering = ("-changed_at",)

    def get_queryset(self):
        queryset = super().get_queryset()
        for_user = getattr(queryset, "for_user", None)
        return queryset


class LeadNoteViewSet(BaseModelViewSet):
    """``/api/v1/lead-notes/``"""

    queryset = LeadNote.active.select_related("lead", "author").all()
    serializer_class = LeadNoteSerializer
    permission_classes = (CanManageLead,)
    search_fields = ("text", "lead__full_name")
    ordering_fields = ("created_at",)
    ordering = ("-created_at",)
    filterset_class = LeadNoteFilter

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self._can_see_all():
            queryset = queryset.filter(lead__branch_id=self.request.user.branch_id)
        return queryset

    def _can_see_all(self) -> bool:
        user = self.request.user
        return user.is_superuser or user.role in ("super_admin", "branch_admin")

    def perform_create(self, serializer) -> None:
        serializer.save(author=self.request.user)


class LeadCallViewSet(BaseModelViewSet):
    """``/api/v1/lead-calls/``"""

    queryset = LeadCall.active.select_related("lead", "caller").all()
    serializer_class = LeadCallSerializer
    permission_classes = (CanManageLead,)
    search_fields = ("comment", "lead__full_name", "lead__phone")
    ordering_fields = ("called_at", "created_at")
    ordering = ("-called_at",)
    filterset_class = LeadCallFilter

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if not (user.is_superuser or user.role in ("super_admin", "branch_admin")):
            queryset = queryset.filter(lead__branch_id=user.branch_id)
        return queryset

    def perform_create(self, serializer) -> None:
        serializer.save(caller=self.request.user)


class LeadFollowUpViewSet(BaseModelViewSet):
    """``/api/v1/lead-follow-ups/``"""

    queryset = LeadFollowUp.objects.select_related("lead", "assigned_to").all()
    serializer_class = LeadFollowUpSerializer
    permission_classes = (CanManageLead,)
    search_fields = ("note", "lead__full_name", "lead__phone")
    ordering_fields = ("due_at", "status", "created_at")
    ordering = ("due_at",)
    filterset_class = LeadFollowUpFilter

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if not (user.is_superuser or user.role in ("super_admin", "branch_admin")):
            queryset = queryset.filter(lead__branch_id=user.branch_id)
        return queryset

    def perform_destroy(self, instance) -> None:
        from common.exceptions import BusinessRuleError

        if instance.status != "pending":
            raise BusinessRuleError(
                detail="Bajarilgan eslatmani o'chirib bo'lmaydi.", code="follow_up_closed"
            )
        instance.delete()

    @extend_schema(request=None, responses=LeadFollowUpSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        follow_up = self.get_object()
        follow_up = LeadService.complete_follow_up(
            follow_up, comment=request.data.get("comment", "")
        )
        return Response(LeadFollowUpSerializer(follow_up).data)
