"""Views for lessons and attendance marking."""
from __future__ import annotations

from datetime import date

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.pagination import CompactPagination
from common.permissions import IsManagerOrAbove, IsTeacher
from common.views import BaseModelViewSet, BaseReadOnlyViewSet

from .filters import AttendanceRecordFilter, LessonFilter
from .models import AttendanceRecord, Lesson, LessonStatus
from .serializers import (
    AttendanceRecordSerializer,
    AttendanceReportSerializer,
    BulkAttendanceSerializer,
    DailyAttendanceReportSerializer,
    GenerateScheduleSerializer,
    LessonListSerializer,
    LessonSerializer,
    LessonWriteSerializer,
)
from .services import AttendanceService, LessonService


class LessonViewSet(BaseModelViewSet):
    """``/api/v1/lessons/``"""

    queryset = Lesson.active.all()
    serializer_class = LessonSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("topic", "group__name", "group__course__name")
    ordering_fields = ("date", "start_time", "status", "created_at")
    ordering = ("-date", "start_time")
    filterset_class = LessonFilter
    pagination_class = CompactPagination
    serializer_class_map = {
        "list": LessonListSerializer,
        "retrieve": LessonSerializer,
        "create": LessonWriteSerializer,
        "update": LessonWriteSerializer,
        "partial_update": LessonWriteSerializer,
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in ("retrieve", "sheet", "records"):
            return queryset.with_related().with_counts().prefetch_related(
                "records__student", "records__marked_by"
            )
        return queryset.with_related()

    def get_permissions(self):
        if self.action in ("list", "retrieve", "today", "records", "options"):
            return [IsAuthenticated()]
        return [IsTeacher()]

    def perform_create(self, serializer) -> None:
        payload = dict(serializer.validated_data)
        lesson = LessonService.create_lesson(payload, actor=self.request.user)
        serializer.instance = lesson

    def perform_update(self, serializer) -> None:
        LessonService.update_lesson(serializer.instance, serializer.validated_data)
        serializer.save()

    @extend_schema(responses=LessonListSerializer(many=True), description="Bugungi darslar")
    @action(detail=False, methods=["get"])
    def today(self, request):
        lessons = LessonService.today_lessons(branch_id=request.query_params.get("branch_id"))
        return Response(LessonListSerializer(lessons, many=True).data)

    @extend_schema(responses=AttendanceRecordSerializer(many=True),
                   description="Dars bo'yicha davomat varaqasi")
    @action(detail=True, methods=["get"], url_path="sheet")
    def sheet(self, request, pk=None):
        lesson = self.get_object()
        records = lesson.records.filter(is_active=True).select_related("student", "marked_by")
        return Response(AttendanceRecordSerializer(records, many=True).data)

    @extend_schema(request=BulkAttendanceSerializer, responses=AttendanceRecordSerializer(many=True),
                   description="Davomatni o'chirish (keldi/kelmadi/kechikdi)")
    @action(detail=True, methods=["post"], url_path="mark")
    def mark(self, request, pk=None):
        lesson = self.get_object()
        serializer = BulkAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        records = AttendanceService.bulk_mark(
            lesson, serializer.validated_data["records"], actor=request.user
        )
        return Response(AttendanceRecordSerializer(records, many=True).data)

    @extend_schema(request=None, responses=AttendanceRecordSerializer(many=True),
                   description="Barcha o'quvchilarni 'keldi' deb belgilash")
    @action(detail=True, methods=["post"], url_path="mark-all-present")
    def mark_all_present(self, request, pk=None):
        lesson = self.get_object()
        records = AttendanceService.mark_all_present(lesson, actor=request.user)
        return Response(AttendanceRecordSerializer(records, many=True).data)

    @extend_schema(request=GenerateScheduleSerializer, responses=LessonListSerializer(many=True),
                   description="Guruh jadvali asosida darslarni avtomatik yaratish")
    @action(detail=True, methods=["post"], url_path="generate-schedule")
    def generate_schedule(self, request, pk=None):
        lesson = self.get_object()
        group = lesson.group
        serializer = GenerateScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lessons = LessonService.generate_lessons_from_schedule(
            group,
            from_date=serializer.validated_data["date_from"],
            to_date=serializer.validated_data["date_to"],
            actor=request.user,
        )
        return Response(LessonListSerializer(lessons, many=True).data, status=201)

    @extend_schema(responses=DailyAttendanceReportSerializer, description="Kunlik davomat hisoboti")
    @action(detail=False, methods=["get"], url_path="daily-report")
    def daily_report(self, request):
        day = request.query_params.get("date")
        report = AttendanceService.daily_report(
            day=date.fromisoformat(day) if day else None,
            branch_id=request.query_params.get("branch_id"),
        )
        return Response(report)


class AttendanceRecordViewSet(BaseReadOnlyViewSet):
    """``/api/v1/attendance/``"""

    queryset = AttendanceRecord.active.select_related("lesson", "student", "marked_by").all()
    serializer_class = AttendanceRecordSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("student__first_name", "student__last_name", "note")
    ordering_fields = ("marked_at", "status")
    ordering = ("-marked_at",)
    filterset_class = AttendanceRecordFilter
    pagination_class = CompactPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_superuser or user.role in ("super_admin", "branch_admin", "manager"):
            branch_id = self.request.query_params.get("branch_id")
            return queryset.filter(lesson__branch_id=branch_id) if branch_id else queryset
        if user.role == "teacher":
            return queryset.filter(
                Q(lesson__teacher=user) | Q(lesson__group__teachers=user)
            ).distinct()
        if user.role == "student":
            return queryset.filter(student__user=user)
        if user.role == "parent":
            return queryset.filter(student__parents=user).distinct()
        return queryset.none()
