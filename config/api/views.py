"""Shared API views (health check, root index)."""
from __future__ import annotations

from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """``GET /api/v1/health/`` — liveness/readiness probe for Docker."""

    permission_classes = (AllowAny,)
    authentication_classes = ()

    @extend_schema(responses=None, description="Service holati")
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            database = "ok"
        except Exception as exc:  # pragma: no cover - infrastructure failure path
            database = f"error: {exc}"
        return Response(
            {
                "status": "ok" if database == "ok" else "degraded",
                "service": "oquv-markazi-crm-api",
                "version": "1.0.0",
                "database": database,
            }
        )


def api_root_view(request):
    """Tiny HTML index pointing to the API, docs and admin."""
    from django.http import HttpResponse

    html = """<!doctype html>
<html lang="uz"><head><meta charset="utf-8"><title>CRM API</title></head>
<body style="font-family:system-ui;padding:40px;line-height:1.8">
<h1>O'quv markazi CRM API</h1>
<ul>
  <li><a href="/api/v1/">API v1 root</a></li>
  <li><a href="/api/v1/health/">Health check</a></li>
  <li><a href="/api/docs/">Swagger UI</a></li>
  <li><a href="/api/redoc/">ReDoc</a></li>
  <li><a href="/api/auth/login/">Login (JWT)</a></li>
  <li><a href="/admin/">Django admin</a></li>
</ul>
</body></html>"""
    return HttpResponse(html)
