"""Dashboard endpoints (aggregated, read-only)."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsManagement, IsStaffMember
from common.views import BaseViewSet

from .services import (
    AttendanceAnalyticsService,
    DashboardService,
    GroupAnalyticsService,
    LeadAnalyticsService,
    PaymentAnalyticsService,
    StudentAnalyticsService,
    TeacherLoadService,
)


class DashboardViewSet(BaseViewSet):
    """``/api/v1/dashboard/`` — aggregated statistics."""

    queryset = None
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        action_name = getattr(self, "action", None)
        if action_name in ("teachers", "groups", "leads", "payments", "attendance", "students"):
            return [IsStaffMember()]
        return [IsManagement()]

    # -- endpoints ---------------------------------------------------------
    @extend_schema(responses=None, description="Asosiy dashboard: CRM, o'quvchi, guruh, moliya, davomat")
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        return Response(DashboardService.summary(request.user, request.query_params))

    @extend_schema(responses=None, description="Leadlar konversiyasi, manbalar kesimida")
    @action(detail=False, methods=["get"])
    def leads(self, request):
        return Response(LeadAnalyticsService.report(request.user, request.query_params))

    @extend_schema(responses=None, description="To'lovlar: yig'ilgan, qarz, oylar kesimida")
    @action(detail=False, methods=["get"])
    def payments(self, request):
        return Response(PaymentAnalyticsService.report(request.user, request.query_params))

    @extend_schema(responses=None, description="Guruhlar to'ldirilganligi")
    @action(detail=False, methods=["get"])
    def groups(self, request):
        return Response(GroupAnalyticsService.report(request.user, request.query_params))

    @extend_schema(responses=None, description="O'qituvchilar yuklamasi (soat/guruh/o'quvchi)")
    @action(detail=False, methods=["get"])
    def teachers(self, request):
        return Response(TeacherLoadService.report(request.user, request.query_params))

    @extend_schema(responses=None, description="Davomat statistikasi")
    @action(detail=False, methods=["get"])
    def attendance(self, request):
        return Response(AttendanceAnalyticsService.report(request.user, request.query_params))

    @extend_schema(responses=None, description="O'quvchilar statistikasi")
    @action(detail=False, methods=["get"])
    def students(self, request):
        return Response(StudentAnalyticsService.report(request.user, request.query_params))
