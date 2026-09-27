"""Views for students, enrollments and nested endpoints."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.groups.models import Group
from common.exceptions import NotFoundError
from common.pagination import CompactPagination
from common.permissions import IsManagerOrAbove
from common.views import BaseModelViewSet

from .filters import EnrollmentFilter, StudentFilter
from .models import Enrollment, Student, StudentStatus
from .serializers import (
    EnrollmentMoveSerializer,
    EnrollmentSerializer,
    EnrollmentWriteSerializer,
    StudentListSerializer,
    StudentSerializer,
    StudentStatusChangeSerializer,
    StudentWriteSerializer,
)
from .services import EnrollmentService, StudentService


class StudentViewSet(BaseModelViewSet):
    """``/api/v1/students/``"""

    queryset = Student.active.all()
    serializer_class = StudentSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("first_name", "last_name", "phone", "email", "telegram_id")
    ordering_fields = ("last_name", "first_name", "start_date", "status", "created_at")
    ordering = ("last_name", "first_name")
    filterset_class = StudentFilter
    pagination_class = CompactPagination
    serializer_class_map = {
        "list": StudentListSerializer,
        "retrieve": StudentSerializer,
        "create": StudentWriteSerializer,
        "update": StudentWriteSerializer,
        "partial_update": StudentWriteSerializer,
        "enrollments": EnrollmentSerializer,
    }

    def get_queryset(self):
        return super().get_queryset().with_related().with_counts()

    def get_serializer_class(self):
        if self.action == "payment_history":
            from apps.payments.serializers import PaymentSerializer

            return PaymentSerializer
        return super().get_serializer_class()

    def get_permissions(self):
        if self.action in ("list", "retrieve", "payment_history", "enrollments", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def perform_create(self, serializer) -> None:
        serializer.save()

    def perform_update(self, serializer) -> None:
        serializer.save()

    def perform_destroy(self, instance) -> None:
        StudentService.delete_student(instance)

    @extend_schema(request=StudentStatusChangeSerializer, responses=StudentSerializer)
    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        student = self.get_object()
        serializer = StudentStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = StudentService.set_status(
            student,
            serializer.validated_data["status"],
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(StudentSerializer(student).data)

    @extend_schema(responses=EnrollmentSerializer(many=True), description="O'quvchining guruhlari")
    @action(detail=True, methods=["get"], url_path="enrollments")
    def enrollments(self, request, pk=None):
        student = self.get_object()
        queryset = student.enrollments.all().select_related("group", "group__course")
        return Response(EnrollmentSerializer(queryset, many=True).data)

    @extend_schema(responses=None, description="O'quvchining to'lov tarixi (nested)")
    @action(detail=True, methods=["get"], url_path="payment-history")
    def payment_history(self, request, pk=None):
        from apps.payments.serializers import PaymentSerializer

        student = self.get_object()
        payments = student.payments.filter(is_active=True).select_related(
            "enrollment", "received_by"
        )
        return Response(PaymentSerializer(payments, many=True).data)

    @extend_schema(responses=None, description="O'quvchi balansi: to'lov/qarz hisobi")
    @action(detail=True, methods=["get"], url_path="balance")
    def balance(self, request, pk=None):
        from apps.payments.services import DebtService

        student = self.get_object()
        return Response(DebtService.student_summary(student))

    @extend_schema(responses=None, description="Guruhga o'quvchi qo'shish (nested)")
    @action(detail=True, methods=["post"], url_path="enroll")
    def enroll_action(self, request, pk=None):
        student = self.get_object()
        serializer = EnrollmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = {**serializer.validated_data, "student": student}
        enrollment = EnrollmentService.enroll(payload, actor=request.user)
        return Response(EnrollmentSerializer(enrollment).data)


class EnrollmentViewSet(BaseModelViewSet):
    """``/api/v1/enrollments/``"""

    queryset = Enrollment.active.all()
    serializer_class = EnrollmentSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("student__first_name", "student__last_name", "group__name")
    ordering_fields = ("start_date", "status", "created_at")
    ordering = ("-created_at",)
    filterset_class = EnrollmentFilter
    pagination_class = CompactPagination
    serializer_class_map = {
        "create": EnrollmentWriteSerializer,
        "update": EnrollmentWriteSerializer,
        "partial_update": EnrollmentWriteSerializer,
    }

    def get_queryset(self):
        return super().get_queryset().with_related()

    def get_permissions(self):
        if self.action in ("list", "retrieve", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def perform_create(self, serializer) -> None:
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer) -> None:
        serializer.save()

    @extend_schema(request=EnrollmentMoveSerializer, responses=EnrollmentSerializer)
    @action(detail=True, methods=["post"], url_path="move")
    def move(self, request, pk=None):
        enrollment = self.get_object()
        serializer = EnrollmentMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = Group.objects.filter(pk=serializer.validated_data["group"]).first()
        if group is None:
            raise NotFoundError(detail="Yangi guruh topilmadi.")
        moved = EnrollmentService.change_group(enrollment, group, actor=request.user)
        return Response(EnrollmentSerializer(moved).data)

    @extend_schema(request=None, responses=EnrollmentSerializer)
    @action(detail=True, methods=["post"], url_path="pause")
    def pause(self, request, pk=None):
        enrollment = EnrollmentService.pause(self.get_object())
        return Response(EnrollmentSerializer(enrollment).data)

    @extend_schema(request=None, responses=EnrollmentSerializer)
    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        enrollment = EnrollmentService.pause(self.get_object(), resume=True)
        return Response(EnrollmentSerializer(enrollment).data)

    @extend_schema(request=None, responses=EnrollmentSerializer, description="Guruhdan chiqarish")
    @action(detail=True, methods=["post"], url_path="leave")
    def leave(self, request, pk=None):
        enrollment = EnrollmentService.unenroll(
            self.get_object(), reason=request.data.get("reason", "")
        )
        return Response(EnrollmentSerializer(enrollment).data)
