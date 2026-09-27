"""Business logic for accounts (thin, testable service layer)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from django.contrib.auth import authenticate
from django.db import transaction

from common.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from common.services import BaseService

from .constants import MANAGEMENT_ROLES, Role
from .models import User, UserActivity


class UserService(BaseService):
    model = User

    #: roles that must be attached to a branch
    BRANCH_REQUIRED_ROLES = (Role.BRANCH_ADMIN, Role.MANAGER, Role.TEACHER)

    @classmethod
    def create_user(cls, data: Dict[str, Any], *, actor: Optional[User] = None) -> User:
        payload = cls.cleanup(data)
        password = payload.pop("password", None)
        if not password:
            password = User.objects.make_random_password()

        role = payload.get("role", Role.STUDENT)
        if role not in Role.values:
            raise BusinessRuleError(detail=f"Noma'lum rol: {role}", code="invalid_role")
        if role in cls.BRANCH_REQUIRED_ROLES and not payload.get("branch"):
            raise BusinessRuleError(
                detail=f"{role} roli uchun filial tanlash majburiy.", code="branch_required"
            )
        if actor is not None and not cls._can_assign_role(actor, role):
            raise PermissionDeniedError(detail="Bu roli tayinlash huquqi yo'q.", code="role_forbidden")

        with cls.atomic():
            user = User.objects.create_user(
                username=payload.get("username") or cls._username_from(payload),
                email=payload.get("email"),
                password=password,
                **payload,
            )
            cls.log(user, UserActivity.Action.CREATED, actor=actor)
        return user

    @classmethod
    def update_user(cls, instance: User, data: Dict[str, Any], *, actor: Optional[User] = None) -> User:
        payload = cls.cleanup(data)
        new_role = payload.get("role", instance.role)
        if actor is not None and not cls._can_assign_role(actor, new_role):
            raise PermissionDeniedError(detail="Bu roli tayinlash huquqi yo'q.", code="role_forbidden")
        if new_role in cls.BRANCH_REQUIRED_ROLES and not payload.get("branch", instance.branch_id):
            raise BusinessRuleError(
                detail="Filial tanlash majburiy.", code="branch_required"
            )
        password = payload.pop("password", None)
        with cls.atomic():
            for field, value in payload.items():
                setattr(instance, field, value)
            if password:
                instance.set_password(password)
            instance.save()
            cls.log(instance, UserActivity.Action.UPDATED, actor=actor)
        return instance

    @classmethod
    def set_password(cls, instance: User, new_password: str, *, actor: Optional[User] = None) -> User:
        instance.set_password(new_password)
        instance.save(update_fields=["password", "updated_at"])
        cls.log(instance, UserActivity.Action.PASSWORD_CHANGE, actor=actor)
        return instance

    @classmethod
    def set_role(cls, instance: User, role: str, *, branch_id: Optional[int] = None,
                 actor: Optional[User] = None) -> User:
        if role not in Role.values:
            raise BusinessRuleError(detail=f"Noma'lum rol: {role}", code="invalid_role")
        if role in cls.BRANCH_REQUIRED_ROLES:
            branch_id = branch_id or instance.branch_id
            if not branch_id:
                raise BusinessRuleError(detail="Filial tanlash majburiy.", code="branch_required")
        instance.role = role
        if branch_id:
            instance.branch_id = branch_id
        instance.is_staff = role in (Role.SUPER_ADMIN, Role.BRANCH_ADMIN)
        instance.save(update_fields=["role", "branch", "is_staff", "updated_at"])
        cls.log(instance, UserActivity.Action.UPDATED, actor=actor, payload={"role": role})
        return instance

    @classmethod
    def deactivate(cls, instance: User, *, actor: Optional[User] = None) -> User:
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        cls.log(instance, UserActivity.Action.DELETED, actor=actor)
        return instance

    @classmethod
    def authenticate_user(cls, username: str, password: str) -> User:
        user = authenticate(username=username, password=password)
        if user is None:
            raise NotFoundError(detail="Login yoki parol noto'g'ri.", code="invalid_credentials")
        if not user.is_active:
            raise PermissionDeniedError(detail="Akkaunt bloklangan.", code="account_inactive")
        return user

    @classmethod
    def permissions_for(cls, user: User) -> list[str]:
        permissions = sorted(user.get_all_permissions())
        role_permissions = {
            Role.SUPER_ADMIN: ["*"],
            Role.BRANCH_ADMIN: [
                "users.read_branch", "users.write_branch", "leads.manage", "students.manage",
                "groups.manage", "payments.read", "payments.write", "analytics.read",
            ],
            Role.MANAGER: [
                "leads.manage", "students.manage", "groups.manage", "payments.read",
                "payments.write", "analytics.read",
            ],
            Role.TEACHER: ["groups.read_own", "attendance.mark_own", "students.read_own_group"],
            Role.STUDENT: ["self.read", "attendance.read_own", "payments.read_own"],
            Role.PARENT: ["children.read", "attendance.read_children", "payments.read_children"],
        }
        return permissions or role_permissions.get(user.role, [])

    @classmethod
    def log(
        cls,
        user: User,
        action: str,
        *,
        actor: Optional[User] = None,
        ip: Optional[str] = None,
        user_agent: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> UserActivity:
        return UserActivity.objects.create(
            user=user,
            action=action,
            ip_address=ip or (actor.last_login_ip if actor else None),
            user_agent=user_agent[:255],
            payload=payload or {},
        )

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _can_assign_role(actor: Optional[User], role: str) -> bool:
        if actor is None or actor.is_superuser or actor.role == Role.SUPER_ADMIN:
            return True
        if actor.role == Role.BRANCH_ADMIN:
            return role in (Role.MANAGER, Role.TEACHER, Role.STUDENT, Role.PARENT)
        return False

    @staticmethod
    def _username_from(payload: Dict[str, Any]) -> str:
        parts = [payload.get("first_name", ""), payload.get("last_name", "")]
        base = ".".join(part for part in parts if part).strip().lower().replace(" ", ".")
        if not base:
            base = payload.get("email", "").split("@")[0]
        if not base:
            raise BusinessRuleError(detail="Login (username) kiritish majburiy.", code="username_required")
        return base


class AuthService(BaseService):
    """JWT login flow helpers."""

    @classmethod
    def login(cls, username: str, password: str, *, ip: Optional[str] = None,
              user_agent: str = "") -> User:
        user = UserService.authenticate_user(username, password)
        user.record_login(ip)
        UserService.log(
            user,
            UserActivity.Action.LOGIN,
            ip=ip,
            user_agent=user_agent,
        )
        return user

    @classmethod
    @transaction.atomic
    def register_student_portal_user(cls, data: Dict[str, Any]) -> User:
        return UserService.create_user({**data, "role": Role.STUDENT})
