"""Thin, reusable DRF viewsets.

Views only translate HTTP <-> service calls; all business rules live in the
``services.py`` of each app.
"""
from __future__ import annotations

from typing import Dict, Type

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated

from common.mixins import (
    ActiveOnlyMixin,
    AuditFieldsMixin,
    ScopedQuerysetMixin,
    SoftDeleteMixin,
)
from common.pagination import StandardPagination


class BaseViewSet(ScopedQuerysetMixin, viewsets.GenericViewSet):
    """Common configuration for every viewset in the project."""

    permission_classes = (IsAuthenticated,)
    pagination_class = StandardPagination
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    serializer_class_map: Dict[str, Type] = {}

    def get_serializer_class(self) -> Type:
        mapping: Dict[str, Type] = getattr(self, "serializer_class_map", {}) or {}
        if self.action in mapping:
            return mapping[self.action]
        return super().get_serializer_class()


class BaseModelViewSet(ActiveOnlyMixin, AuditFieldsMixin, SoftDeleteMixin, BaseViewSet):
    """Full CRUD viewset with role scoping, soft delete and audit fields."""

    search_fields: tuple = ()
    ordering_fields = ("created_at", "updated_at", "id")
    ordering = ("-created_at",)


class BaseReadOnlyViewSet(ActiveOnlyMixin, BaseViewSet):
    """Read-only viewset (reports, catalogs, dashboards)."""

    search_fields: tuple = ()
    ordering_fields = ("created_at", "updated_at", "id")
    ordering = ("-created_at",)


class ToggleActiveViewSet(BaseModelViewSet):
    """Adds ``POST /{id}/toggle-active/`` to soft-delete/restore rows."""

    @extend_schema(request=None, responses={status.HTTP_200_OK: None})
    def toggle_active(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = not instance.is_active
        instance.save(update_fields=["is_active", "updated_at"])
        return self.retrieve(request, *args, **kwargs)
