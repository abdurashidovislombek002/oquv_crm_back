"""Views for groups (CRUD + nested students + schedule management)."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.exceptions import BusinessRuleError
from common.pagination import CompactPagination
from common.permissions import IsManagerOrAbove, IsSuperAdmin
from common.views import BaseModelViewSet

from .filters import GroupFilter
from .models import Group, GroupSchedule
from .serializers import (
    GroupDetailSerializer,
    GroupListSerializer,
    GroupScheduleInputSerializer,
    GroupScheduleSerializer,
    GroupWriteSerializer,
)
from .services import GroupService


class GroupViewSet(BaseModelViewSet):
    """``/api/v1/groups/``"""

    queryset = Group.active.all()
    serializer_class = GroupDetailSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("name", "code", "course__name", "level__name")
    ordering_fields = ("name", "start_date", "capacity", "status", "created_at")
    ordering = ("-created_at",)
    filterset_class = GroupFilter
    pagination_class = CompactPagination
    serializer_class_map = {
        "list": GroupListSerializer,
        "retrieve": GroupDetailSerializer,
        "create": GroupWriteSerializer,
        "update": GroupWriteSerializer,
        "partial_update": GroupWriteSerializer,
        "schedule": GroupScheduleSerializer,
    }

    def get_queryset(self):
        return super().get_queryset().with_related().with_counts()

    def get_permissions(self):
        if self.action in ("list", "retrieve", "schedule", "free_seats", "conflicts", "options"):
            return [IsAuthenticated()]
        if self.action in ("create", "destroy", "patch", "put", "post", "delete"):
            return [IsManagerOrAbove()]
        return [IsAuthenticated()]

    def perform_create(self, serializer) -> None:
        serializer.save()

    def perform_update(self, serializer) -> None:
        serializer.save()

    # -- nested ------------------------------------------------------------
    @extend_schema(
        responses=GroupScheduleSerializer(many=True),
        description="Guruh haftalik jadvali (dars kunlari va vaqtlari)",
    )
    @action(detail=True, methods=["get", "put"], url_path="schedule")
    def schedule(self, request, pk=None):
        group = self.get_object()
        if request.method == "GET":
            return Response(GroupScheduleSerializer(group.schedule.filter(is_active=True), many=True).data)

        serializer = GroupScheduleInputSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        GroupService.replace_schedule(group, serializer.validated_data)
        group.refresh_from_db()
        return Response(GroupScheduleSerializer(group.schedule.filter(is_active=True), many=True).data)

    @extend_schema(description="Guruhga yozilgan o'quvchilar ro'yxati (nested)")
    @action(detail=True, methods=["get"], url_path="students")
    def students(self, request, pk=None):
        from apps.students.serializers import StudentListSerializer

        group = self.get_object()
        students = GroupService.group_students(group)
        return Response(StudentListSerializer(students, many=True).data)

    @extend_schema(description="Guruh bandligi / jadval mojarolari")
    @action(detail=True, methods=["get"], url_path="conflicts")
    def conflicts(self, request, pk=None):
        group = self.get_object()
        return Response({"group": group.name, "conflicts": GroupService.find_conflicts(group)})

    @extend_schema(request=None, responses=None, description="Guruhni faollashtirish")
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        group = GroupService.activate_group(self.get_object())
        return Response(GroupDetailSerializer(group).data)

    @extend_schema(request=None, responses=None, description="Guruhni tugagan deb belgilash")
    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        group = GroupService.finish_group(self.get_object())
        return Response(GroupDetailSerializer(group).data)

    @extend_schema(description="Sig'imi to'lmagan guruhlar")
    @action(detail=False, methods=["get"], url_path="free-seats")
    def free_seats(self, request):
        report = GroupService.fill_rate_report(branch_id=request.query_params.get("branch_id"))
        return Response([row for row in report if row["free_seats"] > 0])

    @extend_schema(description="Guruhlar to'ldirilganlik hisoboti")
    @action(detail=False, methods=["get"], url_path="fill-rate")
    def fill_rate(self, request):
        return Response(GroupService.fill_rate_report(branch_id=request.query_params.get("branch_id")))

    @extend_schema(
        request=GroupScheduleInputSerializer(many=True),
        responses=GroupScheduleSerializer(many=True),
        description="Jadvalga yangi qator qo'shish",
    )
    @action(detail=True, methods=["post"], url_path="schedule/add")
    def schedule_add(self, request, pk=None):
        group = self.get_object()
        serializer = GroupScheduleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        GroupService.add_schedule_slot(group, serializer.validated_data)
        conflicts = GroupService.find_conflicts(group)
        if conflicts:
            raise BusinessRuleError(detail="; ".join(conflicts), code="schedule_conflict",
                                    errors={"conflicts": conflicts})
        return Response(GroupScheduleSerializer(group.schedule.filter(is_active=True), many=True).data)

    @extend_schema(responses={204: None}, description="Jadval qatorini o'chirish")
    @action(detail=True, methods=["delete"], url_path=r"schedule/(?P<slot_id>[0-9]+)")
    def schedule_remove(self, request, pk=None, slot_id=None):
        group = self.get_object()
        GroupService.remove_schedule_slot(group, int(slot_id))
        return Response(status=204)
