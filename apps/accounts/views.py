"""Accounts API: user directory, profile and role management."""
from __future__ import annotations

from django.contrib.auth.mixins import AccessMixin
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from common.mixins import ActiveOnlyMixin, ScopedQuerysetMixin
from common.pagination import CompactPagination
from common.views import BaseModelViewSet, BaseReadOnlyViewSet

from .filters import UserActivityFilter, UserFilter
from .models import User, UserActivity
from .permissions import CanManageUsers, IsSelfOrManager
from .serializers import (
    ChangePasswordSerializer,
    MeSerializer,
    SetRoleSerializer,
    TokenObtainPairCustomSerializer,
    UserActivitySerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserListSerializer,
    UserUpdateSerializer,
)
from .services import UserService


class UserViewSet(BaseModelViewSet):
    """``/api/v1/users/`` — staff directory with role based access."""

    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = (CanManageUsers,)
    filterset_class = UserFilter
    search_fields = ("username", "first_name", "last_name", "phone", "email")
    ordering_fields = ("username", "first_name", "last_name", "role", "created_at", "last_login")
    ordering = ("first_name", "last_name")
    pagination_class = CompactPagination
    serializer_class_map = {
        "list": UserListSerializer,
        "retrieve": UserDetailSerializer,
        "create": UserCreateSerializer,
        "update": UserUpdateSerializer,
        "partial_update": UserUpdateSerializer,
        "me": MeSerializer,
    }

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        if self.action in ("update", "partial_update") and not self._can_edit_other_users():
            # a non-manager may only edit their own limited fields
            for field in ("role", "branch", "is_active", "username", "email", "notes"):
                serializer.fields[field].read_only = True
        return serializer

    def _can_edit_other_users(self) -> bool:
        user = self.request.user
        return user.is_superuser or user.role in ("super_admin", "branch_admin")

    def perform_create(self, serializer) -> None:
        user = UserService.create_user(
            serializer.validated_data, actor=self.request.user
        )
        serializer.instance = user

    def perform_update(self, serializer) -> None:
        UserService.update_user(
            serializer.instance, serializer.validated_data, actor=self.request.user
        )

    def perform_destroy(self, instance) -> None:
        UserService.deactivate(instance, actor=self.request.user)

    @extend_schema(responses=MeSerializer, description="Joriy foydalanuvchi profili")
    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        instance = request.user
        if request.method == "PATCH":
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(self.get_serializer(instance).data)

    @extend_schema(request=SetRoleSerializer, responses=UserDetailSerializer)
    @action(detail=True, methods=["post"], url_path="set-role")
    def set_role(self, request, pk=None):
        user = self.get_object()
        serializer = SetRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = UserService.set_role(
            user,
            role=serializer.validated_data["role"],
            branch_id=getattr(serializer.validated_data.get("branch"), "id", None),
            actor=request.user,
        )
        return Response(UserDetailSerializer(user).data)

    @extend_schema(request=ChangePasswordSerializer, responses={204: None})
    @action(detail=True, methods=["post"], url_path="change-password")
    def change_password(self, request, pk=None):
        user = self.get_object()
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if user.pk != request.user.pk and not (
            request.user.is_superuser or request.user.role in ("super_admin", "branch_admin")
        ):
            from common.exceptions import PermissionDeniedError

            raise PermissionDeniedError(detail="Boshqa foydalanuvchi parolini o'zgartira olmaysiz.")
        if serializer.validated_data.get("old_password") and user.pk == request.user.pk:
            if not user.check_password(serializer.validated_data["old_password"]):
                from common.exceptions import ValidationError

                raise ValidationError(errors={"old_password": ["Eski parol noto'g'ri."]})
        UserService.set_password(user, serializer.validated_data["new_password"], actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=UserDetailSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active", "updated_at"])
        return Response(UserDetailSerializer(user).data)


class UserActivityViewSet(BaseReadOnlyViewSet):
    """``/api/v1/user-activities/`` — login/audit log."""

    queryset = UserActivity.objects.select_related("user").all()
    serializer_class = UserActivitySerializer
    permission_classes = (IsAuthenticated,)
    filterset_class = UserActivityFilter
    search_fields = ("user__username", "user__first_name", "user__last_name", "ip_address")
    ordering_fields = ("created_at",)
    ordering = ("-created_at",)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_superuser or user.role in ("super_admin", "branch_admin", "manager"):
            return queryset
        return queryset.filter(user=user)


class MyProfileView(GenericAPIView):
    """``GET/PATCH /api/v1/profile/`` — dedicated profile endpoint."""

    serializer_class = MeSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user

    def get(self, request, *args, **kwargs):
        return Response(MeSerializer(request.user).data)

    def patch(self, request, *args, **kwargs):
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class LoginView(TokenObtainPairView):
    """``POST /api/auth/login/`` -> access/refresh tokens + user profile."""

    serializer_class = TokenObtainPairCustomSerializer
    permission_classes = ()
    throttle_scope = "auth"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        return response


class LogoutView(APIView):
    """``POST /api/auth/logout/`` — logs the user activity (JWT is stateless)."""

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        from .models import UserActivity

        UserService.log(
            request.user,
            UserActivity.Action.LOGOUT,
            ip=self.get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def get_client_ip(request) -> str:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


class MyPermissionsView(GenericAPIView):
    """``GET /api/auth/permissions/`` — effective permissions of the current user."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        return Response(
            {
                "role": request.user.role,
                "role_display": request.user.get_role_display(),
                "branch": request.user.branch_id,
                "permissions": UserService.permissions_for(request.user),
            }
        )
