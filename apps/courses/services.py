"""Course catalog business logic."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db.models import Count, Q

from common.exceptions import BusinessRuleError
from common.services import BaseService

from .models import Course, CourseLevel


class CourseService(BaseService):
    model = Course

    @classmethod
    def create_course(cls, data: Dict[str, Any]) -> Course:
        payload = cls.cleanup(data)
        if cls.base_queryset().filter(name__iexact=payload.get("name", "")).exists():
            raise BusinessRuleError(detail="Bunday kurs mavjud.", code="duplicate_course")
        return Course.objects.create(**payload)

    @classmethod
    def update_course(cls, instance: Course, data: Dict[str, Any]) -> Course:
        payload = cls.cleanup(data)
        if "name" in payload and cls.base_queryset().exclude(pk=instance.pk).filter(
            name__iexact=payload["name"]
        ).exists():
            raise BusinessRuleError(detail="Bunday kurs mavjud.", code="duplicate_course")
        for field, value in payload.items():
            setattr(instance, field, value)
        instance.save()
        return instance

    @classmethod
    def delete_course(cls, instance: Course) -> None:
        if instance.groups.filter(is_active=True).exists():
            raise BusinessRuleError(
                detail="Kursga faol guruhlar bog'langan. Avval ularni to'xtating.",
                code="course_has_groups",
            )
        instance.soft_delete()

    @classmethod
    def catalog(cls, *, branch_id: Optional[int] = None, category: Optional[str] = None,
                search: Optional[str] = None) -> List[Dict[str, Any]]:
        queryset = Course.active.filter(is_active=True).annotate(
            levels_count=Count("levels", filter=Q(levels__is_active=True), distinct=True),
            groups_count=Count("groups", filter=Q(groups__is_active=True), distinct=True),
        )
        if category:
            queryset = queryset.filter(category__iexact=category)
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        return list(queryset.values("id", "name", "slug", "category", "base_price",
                                    "duration_months", "levels_count", "groups_count"))


class CourseLevelService(BaseService):
    model = CourseLevel

    @classmethod
    def create_level(cls, data: Dict[str, Any]) -> CourseLevel:
        payload = cls.cleanup(data)
        course = payload.get("course")
        if course is None:
            raise BusinessRuleError(detail="Kurs tanlash majburiy.", code="course_required")
        if not payload.get("price"):
            payload["price"] = course.base_price or Decimal("0")
        if CourseLevel.base_queryset().filter(course=course, name__iexact=payload.get("name")).exists():
            raise BusinessRuleError(
                detail="Bu kursda shu nomli daraja mavjud.", code="duplicate_level"
            )
        return CourseLevel.objects.create(**payload)

    @classmethod
    def update_level(cls, instance: CourseLevel, data: Dict[str, Any]) -> CourseLevel:
        payload = cls.cleanup(data)
        for field, value in payload.items():
            setattr(instance, field, value)
        instance.save()
        return instance

    @classmethod
    def delete_level(cls, instance: CourseLevel) -> None:
        if instance.groups.filter(is_active=True).exists():
            raise BusinessRuleError(
                detail="Darajaga faol guruhlar bog'langan.", code="level_has_groups"
            )
        instance.soft_delete()
