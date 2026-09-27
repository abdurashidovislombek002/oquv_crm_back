"""Authentication endpoints (JWT).

    POST /api/auth/login/          -> {access, refresh, user}
    POST /api/auth/refresh/        -> new access token
    POST /api/auth/verify/         -> token validity check
    POST /api/auth/logout/         -> audit log entry
    GET  /api/auth/permissions/    -> effective permissions
    POST /api/auth/password/       -> change own password
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from .serializers import ChangePasswordSerializer
from .views import LogoutView, LoginView, MyPermissionsView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .services import UserService


class MyPasswordView(APIView):
    """``POST /api/auth/password/`` — change own password."""

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        old_password = serializer.validated_data.get("old_password")
        if old_password and not user.check_password(old_password):
            from common.exceptions import ValidationError

            raise ValidationError(errors={"old_password": ["Eski parol noto'g'ri."]})
        UserService.set_password(
            user, serializer.validated_data["new_password"], actor=request.user
        )
        return Response(status=204)


urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("permissions/", MyPermissionsView.as_view(), name="permissions"),
    path("password/", MyPasswordView.as_view(), name="change_own_password"),
]
