"""Branch / Room business logic."""
from __future__ import annotations

from typing import Any, Dict, Optional

from django.db.models import Count, Q

from common.exceptions import BusinessRuleError, NotFoundError
from common.services import BaseService

from .models import Branch, Room


class BranchService(BaseService):
    model = Branch

    @classmethod
    def create_branch(cls, data: Dict[str, Any]) -> Branch:
        payload = cls.cleanup(data)
        code = str(payload.get("code") or "").upper()
        if not code:
            raise BusinessRuleError(detail="Filial kodi majburiy.", code="code_required")
        if cls.base_queryset().filter(code__iexact=code).exists():
            raise BusinessRuleError(detail="Bu kodli filial mavjud.", code="duplicate_code")
        payload["code"] = code
        branch = Branch.objects.create(**payload)
        return branch

    @classmethod
    def update_branch(cls, instance: Branch, data: Dict[str, Any]) -> Branch:
        payload = cls.cleanup(data)
        if "code" in payload:
            payload["code"] = str(payload["code"]).upper()
            if cls.base_queryset().exclude(pk=instance.pk).filter(code__iexact=payload["code"]).exists():
                raise BusinessRuleError(detail="Bu kodli filial mavjud.", code="duplicate_code")
        for field, value in payload.items():
            setattr(instance, field, value)
        instance.save()
        return instance

    @classmethod
    def delete_branch(cls, instance: Branch) -> None:
        """A branch can only be archived (soft delete) — data must be preserved."""
        if instance.groups.filter(is_active=True).exists():
            raise BusinessRuleError(
                detail="Filialda faol guruhlar mavjud. Avval ularni boshqa filialga ko'chiring.",
                code="branch_has_groups",
            )
        instance.soft_delete()

    @classmethod
    def statistics(cls, branch: Optional[Branch] = None) -> Dict[str, Any]:
        groups_qs = Branch.active.filter(is_active=True)
        students_qs = None
        from apps.students.models import Student

        students_qs = Student.active.filter(is_active=True)
        if branch is not None:
            groups_qs = groups_qs.filter(branch=branch)
            students_qs = students_qs.filter(branch=branch)
        branches_qs = Branch.active.filter(is_active=True)
        if branch is not None:
            branches_qs = branches_qs.filter(pk=branch.pk)
        return {
            "branches_count": branches_qs.count(),
            "rooms_count": Room.active.filter(is_active=True).count(),
            "groups_count": groups_qs.count(),
            "students_count": students_qs.count(),
            "rooms_by_branch": list(
                branches_qs.annotate(
                    rooms=Count("rooms", filter=Q(rooms__is_active=True)),
                    groups=Count("groups", filter=Q(groups__is_active=True)),
                ).values("id", "name", "code", "rooms", "groups")
            ),
        }


class RoomService(BaseService):
    model = Room

    @classmethod
    def create_room(cls, data: Dict[str, Any]) -> Room:
        payload = cls.cleanup(data)
        branch = payload.get("branch")
        if branch is None:
            raise BusinessRuleError(detail="Filial tanlash majburiy.", code="branch_required")
        if Room.base_queryset().filter(branch=branch, name=payload.get("name")).exists():
            raise BusinessRuleError(
                detail="Bu filialda shu nomli xona mavjud.", code="duplicate_room"
            )
        return Room.objects.create(**payload)

    @classmethod
    def set_capacity(cls, instance: Room, capacity: int) -> Room:
        """Capacity can never drop below the number of active groups in the room."""
        active_groups = instance.groups.filter(is_active=True).count()
        if capacity < active_groups:
            raise BusinessRuleError(
                detail=f"Xonada {active_groups} ta faol guruh bor, sig'imni kamaytirib bo'lmaydi.",
                code="capacity_too_small",
            )
        instance.capacity = capacity
        instance.save(update_fields=["capacity", "updated_at"])
        return instance

    @classmethod
    def get(cls, pk: Any) -> Room:
        obj = super().get(pk)
        if not isinstance(obj, Room):  # pragma: no cover - defensive
            raise NotFoundError()
        return obj
