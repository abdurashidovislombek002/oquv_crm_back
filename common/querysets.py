"""QuerySets shared by every app: soft-delete awareness + role based scoping."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional

from django.db import models
from django.db.models import Q, QuerySet


class ActiveQuerySet(models.QuerySet):
    """QuerySet that knows about the ``is_active`` (soft delete) flag."""

    def active(self) -> "ActiveQuerySet":
        return self.filter(is_active=True)

    def inactive(self) -> "ActiveQuerySet":
        return self.filter(is_active=False)

    def activate(self) -> int:
        return self.update(is_active=True)

    def deactivate(self) -> int:
        return self.update(is_active=False)

    def bulk_soft_delete(self) -> int:
        return self.deactivate()


class RoleScopedQuerySet(ActiveQuerySet):
    """Role aware queryset.

    Subclasses implement ``scope_<role>(user)`` methods. ``for_user()`` picks the
    right scope based on ``user.role`` so that every API endpoint automatically
    respects row level visibility rules:

    * ``SUPER_ADMIN``   -> everything
    * ``BRANCH_ADMIN``  -> own branch
    * ``MANAGER``       -> own branch
    * ``TEACHER``       -> own groups / own classes
    * ``STUDENT``       -> own data only
    * ``PARENT``        -> own children data only
    """

    #: role value -> scope method suffix. Falls back to ``scope_default``.
    role_scope_map: Dict[str, str] = {}

    def for_user(self, user: Any) -> "RoleScopedQuerySet":
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_superuser", False):
            return self

        role = getattr(user, "role", None)
        scope_name = self.role_scope_map.get(role, "default")
        scope: Optional[Callable[[Any], "RoleScopedQuerySet"]] = getattr(
            self, f"scope_{scope_name}", None
        )
        if scope is None:
            return self.none()
        return scope(user)

    # -- default scopes ----------------------------------------------------
    def scope_default(self, user: Any) -> "RoleScopedQuerySet":
        return self.none()

    def scope_all(self, user: Any) -> "RoleScopedQuerySet":
        return self

    def scope_branch(self, user: Any) -> "RoleScopedQuerySet":
        branch_id = getattr(user, "branch_id", None)
        if not branch_id:
            return self.none()
        return self.filter(branch_id=branch_id)

    # -- helpers -----------------------------------------------------------
    def of_branch(self, branch: Any) -> "RoleScopedQuerySet":
        if branch is None:
            return self
        return self.filter(branch=branch)

    def in_branches(self, branches: Iterable[Any]) -> "RoleScopedQuerySet":
        return self.filter(branch__in=list(branches))

    def distinct_rows(self) -> "RoleScopedQuerySet":
        return self.distinct()


class DateRangeMixin:
    """Convenience filters used by list endpoints (``?date_from=&date_to=``)."""

    def in_date_range(
        self,
        field: str,
        date_from: Any = None,
        date_to: Any = None,
    ) -> "DateRangeMixin":
        queryset: QuerySet = self
        condition = Q()
        if date_from is not None:
            condition |= Q(**{f"{field}__gte": date_from})
        if date_to is not None:
            condition |= Q(**{f"{field}__lte": date_to})
        if condition:
            queryset = queryset.filter(condition)
        return queryset
