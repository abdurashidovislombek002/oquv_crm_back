"""Reusable DRF permission classes (role based + object level)."""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import SAFE_METHODS, BasePermission

MANAGEMENT_ROLES = ("super_admin", "branch_admin", "manager")
SALES_ROLES = ("super_admin", "branch_admin", "manager")
TEACHING_ROLES = ("super_admin", "branch_admin", "manager", "teacher")
LEAD_ROLES = ("super_admin", "branch_admin", "manager")


def has_role(user: Any, *roles: str) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", None) in roles


def in_same_branch(user: Any, obj: Any) -> bool:
    """``True`` when the object belongs to the user's branch (or has no branch)."""
    branch_id = getattr(user, "branch_id", None)
    if branch_id is None:
        return False
    obj_branch_id = getattr(obj, "branch_id", None)
    if obj_branch_id is None:
        # object without branch scoping (e.g. course) -> visible to branch staff
        return True
    return obj_branch_id == branch_id


def is_owner(user: Any, obj: Any) -> bool:
    """Ownership check: ``obj.user``, ``obj.owner`` or ``obj.created_by``."""
    for attr in ("user", "owner", "created_by", "student"):
        candidate = getattr(obj, attr, None)
        if candidate is not None and getattr(candidate, "pk", None) == getattr(user, "pk", None):
            return True
    parents = getattr(obj, "parents", None)
    if parents is not None and parents.filter(pk=user.pk).exists():
        return True
    return False


class IsSuperAdmin(BasePermission):
    """Only ``super_admin`` role (or Django superuser)."""

    message = "Faqat SuperAdmin uchun."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, "super_admin")

    def has_object_permission(self, request, view, obj) -> bool:
        return self.has_permission(request, view)


class IsBranchAdmin(BasePermission):
    """``branch_admin`` and above."""

    message = "Faqat filial admini uchun."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, "super_admin", "branch_admin")

    def has_object_permission(self, request, view, obj) -> bool:
        if not self.has_permission(request, view):
            return False
        if request.user.is_superuser or request.user.role == "super_admin":
            return True
        return in_same_branch(request.user, obj)


class IsManagerOrAbove(BasePermission):
    """``manager`` / ``branch_admin`` / ``super_admin``."""

    message = "Faqat menejer va undan yuqori rol uchun."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, *MANAGEMENT_ROLES)

    def has_object_permission(self, request, view, obj) -> bool:
        if not self.has_permission(request, view):
            return False
        if request.user.role in ("super_admin", "branch_admin") or request.user.is_superuser:
            return True
        return in_same_branch(request.user, obj)


class IsManagement(BasePermission):
    """Any management role — used for read-only analytics endpoints."""

    message = "Faqat rahbariyat uchun."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, *MANAGEMENT_ROLES)


class IsStaffMember(BasePermission):
    """Any internal employee (management + teachers)."""

    message = "Faqat xodimlar uchun."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, *TEACHING_ROLES)

    def has_object_permission(self, request, view, obj) -> bool:
        if not self.has_permission(request, view):
            return False
        if has_role(request.user, "super_admin", "branch_admin"):
            return True
        return in_same_branch(request.user, obj)


class IsTeacher(BasePermission):
    message = "Faqat o'qituvchilar uchun."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, *TEACHING_ROLES)

    def has_object_permission(self, request, view, obj) -> bool:
        if not self.has_permission(request, view):
            return False
        if has_role(request.user, "super_admin", "branch_admin", "manager"):
            return in_same_branch(request.user, obj) or request.user.role == "super_admin"
        teacher = getattr(obj, "teacher", None) or getattr(obj, "created_by", None)
        if teacher is not None and teacher.pk == request.user.pk:
            return True
        teachers = getattr(obj, "teachers", None)
        if teachers is not None and teachers.filter(pk=request.user.pk).exists():
            return True
        return in_same_branch(request.user, obj)


class IsStudentOrParent(BasePermission):
    message = "Faqat o'quvchi/ota-onalar uchun."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, "student", "parent")


class IsOwnerOrStaff(BasePermission):
    """Object level: owner (student/parent/creator) or staff of the same branch."""

    message = "Bu resursga ruxsatingiz yo'q."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if has_role(user, "super_admin"):
            return True
        if is_owner(user, obj):
            return True
        if user.role in ("branch_admin", "manager"):
            return in_same_branch(user, obj)
        if user.role == "teacher":
            if has_role(user, "teacher") and in_same_branch(user, obj):
                return getattr(obj, "branch_id", None) == user.branch_id
        return False


class IsReadOnlyOrManager(BasePermission):
    """Anyone may read (if the queryset allows), only managers may write."""

    message = "O'qishdan tashqari amalni faqat menejer bajaradi."

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return bool(getattr(request.user, "is_authenticated", False))
        return has_role(request.user, *MANAGEMENT_ROLES)

    def has_object_permission(self, request, view, obj) -> bool:
        return self.has_permission(request, view)


class CanManageLead(BasePermission):
    """Sales roles can work with leads; teachers can only see their own."""

    message = "Leadlar bilan ishlash huquqi yo'q."

    def has_permission(self, request, view) -> bool:
        return has_role(request.user, *LEAD_ROLES)

    def has_object_permission(self, request, view, obj) -> bool:
        if not self.has_permission(request, view):
            return False
        if request.user.is_superuser or request.user.role == "super_admin":
            return True
        return in_same_branch(request.user, obj)
