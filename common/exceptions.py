"""Uniform API error format.

Every error response looks like::

    {
      "error": {
        "status_code": 400,
        "code": "validation_error",
        "message": "Request validation failed",
        "details": {"phone": ["Bu telefon raqami allaqachon mavjud."]},
        "request_id": "0f1c..."
      }
    }
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.serializers import ValidationError as DRFValidationError
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

TRUTHY = {"1", "true", "yes", "on"}


class APIError(APIException):
    """Base class for domain errors raised from service classes."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "So'rovni bajarishda xatolik yuz berdi."
    default_code = "api_error"

    def __init__(
        self,
        detail: Optional[str] = None,
        code: Optional[str] = None,
        errors: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(detail or self.default_detail, code or self.default_code)
        self.errors = errors or {}


class BusinessRuleError(APIError):
    """Raised when a domain rule is violated (e.g. group is full)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Amal qoidasi buzildi."
    default_code = "business_rule_error"


class ValidationError(APIError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Validatsiya xatosi."
    default_code = "validation_error"


class ConflictError(APIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Konflikt holati yuz berdi."
    default_code = "conflict"


class NotFoundError(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Obyekt topilmadi."
    default_code = "not_found"


class PermissionDeniedError(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Bu amalni bajarishga ruxsat yo'q."
    default_code = "permission_denied"


def _request_id(context: Optional[Dict[str, Any]]) -> str:
    request = (context or {}).get("request")
    existing = getattr(request, "request_id", None) if request else None
    return existing or uuid.uuid4().hex


def _flatten_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key, value in detail.items():
            message = _flatten_detail(value)
            if message:
                return message if key == "detail" else f"{key}: {message}"
        return str(detail)
    if isinstance(detail, (list, tuple)):
        for item in detail:
            message = _flatten_detail(item)
            if message:
                return message
        return str(detail)
    return str(detail)


def _details_payload(detail: Any) -> Optional[Dict[str, Any]]:
    if isinstance(detail, dict):
        return detail
    return None


def custom_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[Response]:
    """DRF ``EXCEPTION_HANDLER`` producing the standard error envelope."""
    if isinstance(exc, Http404):
        exc = NotFoundError(detail="So'ralgan manzil topilmadi.", code="not_found")
    elif isinstance(exc, DjangoPermissionDenied):
        exc = PermissionDeniedError()
    elif isinstance(exc, DjangoValidationError):
        exc = ValidationError(errors=getattr(exc, "message_dict", None) or {"detail": exc.messages})
    elif isinstance(exc, DRFValidationError):
        exc = ValidationError(errors=exc.detail)

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception: %s", exc)
        return None

    detail = response.data
    code = getattr(exc, "default_code", None) or "error"
    if isinstance(exc, APIError):
        code = getattr(exc, "default_code", code)
        if getattr(exc, "errors", None):
            detail = exc.errors

    payload = {
        "error": {
            "status_code": response.status_code,
            "code": code,
            "message": _flatten_detail(detail),
            "details": _details_payload(detail),
            "request_id": _request_id(context),
        }
    }
    response.data = payload
    return response
