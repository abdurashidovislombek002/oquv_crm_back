"""Permission classes for accounts (re-export + user specific rules)."""
from common.permissions import (  # noqa: F401
    IsBranchAdmin,
    IsManagerOrAbove,
    IsStaffMember,
    IsSuperAdmin,
    in_same_branch,
)
from rest_framework.permissions import SAFE_METHODS, BasePermission


class CanManageUsers(BasePermission):
    """Read: any authenticated user (queryset scoping limits rows).

    Write: superadmin globally, branch_admin inside their branch.
    """

    message = "Foydalanuvchilarni boshqarish huquqi yo'q."

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_superuser or request.user.role in ("super_admin", "branch_admin")

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.is_superuser or user.role == "super_admin":
            return True
        if request.method in SAFE_METHODS:
            return in_same_branch(user, obj) or obj.pk == user.pk
        if user.role == "branch_admin":
            return in_same_branch(user, obj) and obj.role != "super_admin"
        return obj.pk == user.pk


class IsSelfOrManager(BasePermission):
    """Object level: own profile or any management role."""

    message = "Faqat o'z ma'lumotlaringizga kirish mumkin."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if obj.pk == user.pk:
            return True
        return user.is_superuser or user.role in ("super_admin", "branch_admin", "manager")
