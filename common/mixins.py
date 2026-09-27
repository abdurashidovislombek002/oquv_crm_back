"""View mixins: queryset scoping, soft delete, audit fields."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Type

from common.querysets import RoleScopedQuerySet

TRUTHY = {"1", "true", "yes", "on"}


class ScopedQuerysetMixin:
    """Applies role based row-level visibility to every queryset.

    Views only need ``queryset``; the mixin calls ``for_user(request.user)``
    when the queryset implements it (all app querysets derive from
    :class:`common.querysets.RoleScopedQuerySet`).
    """

    #: allow managers to switch branch with ``?branch_id=`` (superadmin only)
    branch_query_param = "branch_id"

    def get_base_queryset(self):
        return self.queryset.all()

    def scope_queryset_for_user(self, queryset, user):
        for_user = getattr(queryset, "for_user", None)
        if callable(for_user):
            return for_user(user)
        return queryset

    def apply_branch_override(self, queryset, user):
        value = self.request.query_params.get(self.branch_query_param)
        if not value:
            return queryset
        if getattr(user, "role", None) == "super_admin" or getattr(user, "is_superuser", False):
            return queryset.filter(branch_id=value)
        if getattr(user, "role", None) in ("branch_admin", "manager"):
            if str(getattr(user, "branch_id", "")) == str(value):
                return queryset
        return queryset.filter(pk__in=[])

    def get_queryset(self):
        queryset = self.scope_queryset_for_user(self.get_base_queryset(), self.request.user)
        queryset = self.apply_branch_override(queryset, self.request.user)
        return queryset


class ActiveOnlyMixin:
    """Hides soft-deleted rows unless explicitly requested by management."""

    def _can_see_inactive(self) -> bool:
        return getattr(self.request.user, "role", None) in (
            "super_admin",
            "branch_admin",
            "manager",
        ) or bool(getattr(self.request.user, "is_superuser", False))

    def _include_inactive_requested(self) -> bool:
        value = self.request.query_params.get("include_inactive", "")
        return str(value).lower() in TRUTHY

    def get_queryset(self):
        queryset = super().get_queryset()
        if "is_active" in {field.name for field in queryset.model._meta.get_fields()}:
            if not (self._can_see_inactive() and self._include_inactive_requested()):
                queryset = queryset.filter(is_active=True)
        return queryset


class AuditFieldsMixin:
    """Injects ``created_by``/``updated_by`` when the model supports them."""

    def _set_audit_fields(self, serializer):
        model = getattr(getattr(serializer, "Meta", None), "model", None)
        if model is None:
            return
        field_names = {field.name for field in model._meta.get_fields()}
        validated = getattr(serializer, "validated_data", None)
        for field in ("created_by", "updated_by"):
            if field not in field_names:
                continue
            if validated is not None and field not in validated:
                validated[field] = self.request.user
            setattr(serializer, field, self.request.user)

    def perform_create(self, serializer):
        self._set_audit_fields(serializer)
        serializer.save()

    def perform_update(self, serializer):
        self._set_audit_fields(serializer)
        serializer.save()


class SoftDeleteMixin:
    """``DELETE`` soft-deletes; ``?hard=1`` permanently removes (superadmin)."""

    def perform_destroy(self, instance) -> None:
        request = getattr(self, "request", None)
        hard = str(request.query_params.get("hard", "")).lower() in TRUTHY if request else False
        if hard and (
            getattr(request.user, "is_superuser", False)
            or getattr(request.user, "role", None) == "super_admin"
        ):
            instance.delete()
            return
        if hasattr(instance, "soft_delete"):
            instance.soft_delete()
        else:  # pragma: no cover - defensive
            instance.delete()
