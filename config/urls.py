"""Root URL configuration.

    /api/v1/...  -> versioned REST API (see config.api.router)
    /api/docs/   -> Swagger UI
    /api/redoc/  -> ReDoc
    /admin/      -> Django admin
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from config.api.router import api_router
from config.api.views import HealthView, api_root_view

urlpatterns = [
    path("", api_root_view, name="api-root"),
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_router.urls)),
    path("api/v1/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("apps.accounts.auth_urls")),
    # OpenAPI / Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
