"""Permission classes specific to branches."""
from common.permissions import IsBranchAdmin, IsManagerOrAbove, IsSuperAdmin, is_owner  # noqa: F401


class CanManageBranch(IsSuperAdmin):
    """Creating branches: superadmin only. Updating: superadmin or that branch's admin."""

    message = "Filialni boshqarish huquqi yo'q."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if getattr(user, "is_superuser", False) or user.role == "super_admin":
            return True
        if user.role == "branch_admin" and obj.pk == user.branch_id:
            return True
        return False
