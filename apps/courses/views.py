"""Views for the course catalog."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsManagerOrAbove, IsSuperAdmin
from common.views import BaseModelViewSet, BaseReadOnlyViewSet

from .filters import CourseFilter, CourseLevelFilter
from .models import Course, CourseLevel
from .serializers import (
    CourseCatalogItemSerializer,
    CourseLevelListSerializer,
    CourseLevelSerializer,
    CourseListSerializer,
    CourseSerializer,
)
from .services import CourseLevelService, CourseService


class CourseViewSet(BaseModelViewSet):
    """``/api/v1/courses/`` — any subject can be added by an administrator."""

    queryset = Course.active.all()
    serializer_class = CourseSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("name", "category", "description")
    ordering_fields = ("name", "ordering", "base_price", "created_at", "is_active")
    ordering = ("ordering", "name")
    filterset_class = CourseFilter
    serializer_class_map = {
        "list": CourseListSerializer,
        "retrieve": CourseSerializer,
        "catalog": CourseCatalogItemSerializer,
    }

    def get_queryset(self):
        return super().get_queryset().prefetch_related("levels")

    def get_permissions(self):
        if self.action in ("list", "retrieve", "catalog", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def perform_create(self, serializer) -> None:
        serializer.instance = CourseService.create_course(serializer.validated_data)

    def perform_update(self, serializer) -> None:
        CourseService.update_course(serializer.instance, serializer.validated_data)
        serializer.save()

    def perform_destroy(self, instance) -> None:
        CourseService.delete_course(instance)

    @extend_schema(
        responses=CourseCatalogItemSerializer(many=True),
        description="Katalog: kurslar soni/levelari/guruhlari bilan",
    )
    @action(detail=False, methods=["get"])
    def catalog(self, request):
        data = CourseService.catalog(
            category=request.query_params.get("category"),
            search=request.query_params.get("search"),
            branch_id=request.query_params.get("branch_id"),
        )
        return Response(data)


class CourseLevelViewSet(BaseModelViewSet):
    """``/api/v1/course-levels/``"""

    queryset = CourseLevel.active.select_related("course").all()
    serializer_class = CourseLevelSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("name", "course__name")
    ordering_fields = ("name", "ordering", "price", "created_at")
    ordering = ("ordering", "name")
    filterset_class = CourseLevelFilter
    serializer_class_map = {"list": CourseLevelListSerializer, "retrieve": CourseLevelSerializer}

    def get_permissions(self):
        if self.action in ("list", "retrieve", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def perform_create(self, serializer) -> None:
        serializer.instance = CourseLevelService.create_level(serializer.validated_data)

    def perform_update(self, serializer) -> None:
        CourseLevelService.update_level(serializer.instance, serializer.validated_data)
        serializer.save()

    def perform_destroy(self, instance) -> None:
        CourseLevelService.delete_level(instance)
