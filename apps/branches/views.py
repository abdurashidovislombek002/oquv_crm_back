"""Views for branches and rooms."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.filters import BaseFilterSet  # noqa: F401
from common.pagination import CompactPagination
from common.views import BaseModelViewSet

from .filters import BranchFilter, RoomFilter
from .models import Branch, Room
from .permissions import CanManageBranch
from .serializers import (
    BranchListSerializer,
    BranchSerializer,
    BranchStatisticsSerializer,
    RoomListSerializer,
    RoomSerializer,
)
from .services import BranchService, RoomService


class BranchViewSet(BaseModelViewSet):
    """``/api/v1/branches/``"""

    queryset = Branch.active.all()
    serializer_class = BranchSerializer
    permission_classes = (CanManageBranch,)
    search_fields = ("name", "code", "address", "phone")
    ordering_fields = ("name", "code", "created_at", "is_active")
    ordering = ("name",)
    filterset_class = BranchFilter
    pagination_class = CompactPagination
    serializer_class_map = {"list": BranchListSerializer, "retrieve": BranchSerializer}

    def get_permissions(self):
        if self.action in ("list", "retrieve", "statistics", "options"):
            return [IsAuthenticated()]
        return [CanManageBranch()]

    def perform_create(self, serializer) -> None:
        branch = BranchService.create_branch(serializer.validated_data)
        serializer.instance = branch

    def perform_update(self, serializer) -> None:
        BranchService.update_branch(serializer.instance, serializer.validated_data)
        serializer.save()

    def perform_destroy(self, instance) -> None:
        BranchService.delete_branch(instance)

    @extend_schema(responses=BranchStatisticsSerializer, description="Filial bo'yicha umumiy statistika")
    @action(detail=False, methods=["get"])
    def statistics(self, request):
        branch = None
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            branch = self.get_queryset().filter(pk=branch_id).first()
        return Response(BranchService.statistics(branch=branch))


class RoomViewSet(BaseModelViewSet):
    """``/api/v1/rooms/``"""

    queryset = Room.active.all()
    serializer_class = RoomSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("name", "code")
    ordering_fields = ("name", "capacity", "created_at", "is_active")
    ordering = ("name",)
    filterset_class = RoomFilter
    pagination_class = CompactPagination
    serializer_class_map = {"list": RoomListSerializer, "retrieve": RoomSerializer}

    def get_permissions(self):
        from common.permissions import IsManagerOrAbove

        if self.action in ("list", "retrieve", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def perform_create(self, serializer) -> None:
        room = RoomService.create_room(serializer.validated_data)
        serializer.instance = room

    @extend_schema(request=None, responses={RoomSerializer})
    @action(detail=True, methods=["post"], url_path="set-capacity")
    def set_capacity(self, request, pk=None):
        room = self.get_object()
        capacity = request.data.get("capacity")
        if capacity is None:
            from common.exceptions import BusinessRuleError

            raise BusinessRuleError(detail="capacity majburiy.", code="capacity_required")
        room = RoomService.set_capacity(room, int(capacity))
        return Response(RoomSerializer(room).data)
