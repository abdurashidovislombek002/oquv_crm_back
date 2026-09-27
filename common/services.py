"""Base service class: transactions, lookups and error handling helpers.

Business logic lives in ``services.py`` files; views stay thin.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, Optional, Type

from django.db import transaction
from django.db.models import Model, QuerySet

from common.exceptions import NotFoundError


class BaseService:
    """Reusable helpers for concrete service classes."""

    model: Optional[Type[Model]] = None

    # -- transactions ------------------------------------------------------
    @staticmethod
    @contextmanager
    def atomic() -> Iterator[None]:
        with transaction.atomic():
            yield

    # -- lookups -----------------------------------------------------------
    @classmethod
    def base_queryset(cls) -> QuerySet:
        if cls.model is None:  # pragma: no cover - programming error
            raise NotImplementedError("Service class must define `model`.")
        return cls.model._default_manager.all()

    @classmethod
    def queryset_for_user(cls, user: Any) -> QuerySet:
        """Role-scoped queryset when available, otherwise the plain queryset."""
        queryset = cls.base_queryset()
        for_user = getattr(queryset, "for_user", None)
        if callable(for_user):
            return for_user(user)
        return queryset

    @classmethod
    def get(cls, pk: Any, *, queryset: Optional[QuerySet] = None) -> Model:
        queryset = queryset if queryset is not None else cls.base_queryset()
        obj = queryset.filter(pk=pk).first() if not isinstance(pk, Model) else pk
        if obj is None:
            raise NotFoundError(detail=f"{cls.model._meta.verbose_name} topilmadi.")
        return obj

    @classmethod
    def get_active(cls, pk: Any) -> Model:
        obj = cls.get(pk)
        if not getattr(obj, "is_active", True):
            raise NotFoundError(detail="Obyekt arxivdan chiqarilgan.")
        return obj

    # -- dict helpers ------------------------------------------------------
    @staticmethod
    def cleanup(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return {key: value for key, value in (data or {}).items() if value is not None}

    @staticmethod
    def bulk_create(model: Type[Model], objects: Iterable[Model], batch_size: int = 500) -> None:
        model._default_manager.bulk_create(list(objects), batch_size=batch_size)
