"""Group business logic: creation, scheduling, conflicts, capacity."""
from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, Iterable, List, Optional

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.branches.models import Room
from common.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from common.services import BaseService
from common.utils import time_to_minutes

from .models import Group, GroupSchedule, GroupStatus


class GroupService(BaseService):
    model = Group

    @classmethod
    @transaction.atomic
    def create_group(cls, data: Dict[str, Any], *, actor: Optional[User] = None) -> Group:
        payload = cls.cleanup(data)
        schedule = payload.pop("schedule", None) or []
        teachers = payload.pop("teachers", None)
        head_teacher = payload.pop("head_teacher", None)
        capacity = payload.get("capacity") or 15

        level = payload.get("level")
        course = payload.get("course") or (level.course if level else None)
        if level is None or course is None:
            raise BusinessRuleError(detail="Kurs va daraja tanlash majburiy.", code="level_required")
        if level.course_id != course.id:
            raise BusinessRuleError(detail="Daraja boshqa kursga tegishli.", code="level_course_mismatch")

        room = payload.get("room")
        branch = payload.get("branch")
        if room is not None and branch is not None and room.branch_id != branch.id:
            raise BusinessRuleError(detail="Xona boshqa filialga tegishli.", code="room_branch_mismatch")

        if payload.get("monthly_fee") is None and level.max_students_per_group:
            capacity = min(capacity, level.max_students_per_group) if payload.get("capacity") else capacity

        group = Group(
            **{**payload, "course": course, "level": level, "capacity": capacity, "created_by": actor}
        )
        group.full_clean(exclude=["created_by"])
        group.save()

        if teachers:
            group.teachers.set(cls._validate_teachers(teachers, branch))
        if head_teacher:
            group.head_teacher = cls._validate_teacher(head_teacher, branch)
            group.save(update_fields=["head_teacher", "updated_at"])
        if schedule:
            cls.replace_schedule(group, schedule)
        cls.assert_no_conflicts(group)
        return group

    @classmethod
    def update_group(cls, instance: Group, data: Dict[str, Any], *, actor: Optional[User] = None) -> Group:
        payload = cls.cleanup(data)
        schedule = payload.pop("schedule", None)
        teachers = payload.pop("teachers", None)
        head_teacher = payload.pop("head_teacher", None)

        branch = payload.get("branch", instance.branch)
        for field, value in payload.items():
            setattr(instance, field, value)
        instance.full_clean(exclude=["created_by"])
        instance.save()

        if teachers is not None:
            instance.teachers.set(cls._validate_teachers(teachers, branch))
        if head_teacher is not None:
            instance.head_teacher = cls._validate_teacher(head_teacher, branch)
            instance.save(update_fields=["head_teacher", "updated_at"])
        if schedule is not None:
            cls.replace_schedule(instance, schedule)
        cls.assert_no_conflicts(instance)
        return instance

    # -- schedule ----------------------------------------------------------
    @classmethod
    def replace_schedule(cls, group: Group, slots: Iterable[Dict[str, Any]]) -> List[GroupSchedule]:
        """Replaces the weekly timetable of a group."""
        with transaction.atomic():
            group.schedule.all().update(is_active=False)
            created: List[GroupSchedule] = []
            for slot in slots:
                created.append(cls.add_schedule_slot(group, slot))
        return created

    @classmethod
    def add_schedule_slot(cls, group: Group, slot: Dict[str, Any]) -> GroupSchedule:
        data = {
            "day_of_week": int(slot.get("day_of_week") or slot.get("weekday") or 0),
            "start_time": slot.get("start_time") or group.start_time,
            "end_time": slot.get("end_time") or group.end_time,
            "room_id": slot.get("room") or group.room_id,
        }
        if not 1 <= data["day_of_week"] <= 7:
            raise BusinessRuleError(detail="Haftaning kuni 1..7 orasida bo'lishi kerak.", code="invalid_weekday")
        if GroupSchedule.active.filter(
            group=group, day_of_week=data["day_of_week"], start_time=data["start_time"]
        ).exists():
            raise BusinessRuleError(
                detail="Bu kunda bunday vaqtda dars allaqachon rejalashtirilgan.", code="duplicate_slot"
            )
        return GroupSchedule.objects.create(group=group, **data)

    @classmethod
    def remove_schedule_slot(cls, group: Group, slot_id: int) -> None:
        slot = cls.get_slot_or_404(group, slot_id)
        slot.soft_delete()

    @classmethod
    def get_slot_or_404(cls, group: Group, slot_id: int) -> GroupSchedule:
        slot = GroupSchedule.objects.filter(pk=slot_id, group=group).first()
        if slot is None:
            raise NotFoundError(detail="Jadval qatori topilmadi.")
        return slot

    # -- conflicts ---------------------------------------------------------
    @classmethod
    def assert_no_conflicts(cls, group: Group) -> None:
        """Room and teacher cannot be double-booked in overlapping time slots."""
        conflicts = cls.find_conflicts(group)
        if conflicts:
            raise BusinessRuleError(
                detail="; ".join(conflicts),
                code="schedule_conflict",
                errors={"conflicts": conflicts},
            )

    @classmethod
    def find_conflicts(cls, group: Group) -> List[str]:
        messages: List[str] = []
        slots = list(group.schedule.filter(is_active=True))
        if not slots:
            return messages

        room_ids = {slot.room_id or group.room_id for slot in slots}
        room_ids.discard(None)
        other_slots = (
            GroupSchedule.active.filter(
                day_of_week__in=[slot.day_of_week for slot in slots],
                room_id__in=room_ids,
            )
            .exclude(group=group)
            .select_related("group", "room")
        )
        for other in other_slots:
            for slot in slots:
                if other.day_of_week != slot.day_of_week:
                    continue
                if cls._overlaps(
                    slot.start_time, slot.end_time, other.start_time, other.end_time
                ):
                    messages.append(
                        f"Xona {other.room.name if other.room else other.group.room} "
                        f"{other.get_day_of_week_display()} {other.time_range} da band"
                    )

        teacher_ids = set(group.teachers.values_list("id", flat=True))
        if group.head_teacher_id:
            teacher_ids.add(group.head_teacher_id)
        if teacher_ids:
            other_groups = Group.active.filter(
                Q(teachers__id__in=teacher_ids) | Q(head_teacher_id__in=teacher_ids)
            ).exclude(pk=group.pk).distinct()
            other_ids = list(other_groups.values_list("id", flat=True))
            if other_ids:
                other_slots = (
                    GroupSchedule.active.filter(group_id__in=other_ids)
                    .select_related("group")
                )
                teacher_names = ", ".join(
                    user.full_name for user in group.teachers.all()
                ) or "o'qituvchi"
                for other in other_slots:
                    for slot in slots:
                        if other.day_of_week != slot.day_of_week:
                            continue
                        if cls._overlaps(
                            slot.start_time, slot.end_time, other.start_time, other.end_time
                        ):
                            messages.append(
                                f"{teacher_names}: {other.group.name} "
                                f"{other.get_day_of_week_display()} {other.time_range}"
                            )
        return list(dict.fromkeys(messages))

    @staticmethod
    def _overlaps(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
        a_start, a_end = time_to_minutes(start_a), time_to_minutes(end_a)
        b_start, b_end = time_to_minutes(start_b), time_to_minutes(end_b)
        if None in (a_start, a_end, b_start, b_end):
            return False
        return a_start < b_end and b_start < a_end

    # -- capacity / students ----------------------------------------------
    @classmethod
    def assert_can_enroll(cls, group: Group, *, exclude_enrollment_id: Optional[int] = None) -> None:
        if group.status == GroupStatus.ARCHIVED:
            raise BusinessRuleError(detail="Arxivlangan guruhga yozilish mumkin emas.", code="group_archived")
        if group.status == GroupStatus.FINISHED:
            raise BusinessRuleError(detail="Tugagan guruhga yozilish mumkin emas.", code="group_finished")
        if group.filled_seats >= group.capacity:
            raise BusinessRuleError(
                detail=f"Guruh to'lgan ({group.filled_seats}/{group.capacity}).", code="group_full"
            )

    @classmethod
    def activate_group(cls, instance: Group) -> Group:
        if not instance.can_start:
            raise BusinessRuleError(
                detail=(
                    f"Guruhni boshlash uchun kamida {instance.min_students} ta o'quvchi kerak "
                    f"(hozir {instance.filled_seats})."
                ),
                code="not_enough_students",
            )
        instance.status = GroupStatus.ACTIVE
        instance.save(update_fields=["status", "updated_at"])
        return instance

    @classmethod
    def finish_group(cls, instance: Group, end_date: Optional[date] = None) -> Group:
        instance.status = GroupStatus.FINISHED
        fields = ["status", "updated_at"]
        if end_date:
            instance.end_date = end_date
            fields.append("end_date")
        instance.save(update_fields=fields)
        from apps.students.models import Enrollment, EnrollmentStatus

        Enrollment.objects.filter(group=instance, status=EnrollmentStatus.ACTIVE).update(
            status=EnrollmentStatus.COMPLETED, end_date=end_date or timezone.localdate()
        )
        return instance

    @classmethod
    def group_students(cls, instance: Group) -> List[Any]:
        from apps.students.models import Enrollment, Student

        return list(
            Student.objects.filter(
                enrollments__group=instance, enrollments__is_active=True
            ).distinct()
        )

    @classmethod
    def fill_rate_report(cls, branch_id: Optional[int] = None) -> List[Dict[str, Any]]:
        queryset = Group.active.filter(is_active=True).with_counts()
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        return [
            {
                "group_id": group.id,
                "group": group.name,
                "branch": group.branch.name,
                "course": group.course.name,
                "capacity": group.capacity,
                "students": group.students_count,
                "free_seats": max(group.capacity - group.students_count, 0),
                "fill_rate": group.fill_rate,
                "status": group.status,
            }
            for group in queryset
        ]

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _validate_teachers(teachers: Iterable[Any], branch: Any) -> List[User]:
        resolved: List[User] = []
        for teacher in teachers:
            resolved.append(GroupService._validate_teacher(teacher, branch))
        if not resolved:
            raise BusinessRuleError(detail="Kamida bitta o'qituvchi tanlang.", code="teacher_required")
        return resolved

    @staticmethod
    def _validate_teacher(teacher: Any, branch: Any) -> User:
        if not isinstance(teacher, User):
            teacher = User.objects.filter(pk=teacher).first()
        if teacher is None:
            raise NotFoundError(detail="O'qituvchi topilmadi.")
        if teacher.role not in (Role.TEACHER, Role.MANAGER, Role.BRANCH_ADMIN) and not teacher.is_superuser:
            raise BusinessRuleError(
                detail=f"{teacher} o'qituvchi roliga ega emas.", code="invalid_teacher_role"
            )
        if branch is not None and teacher.branch_id not in (None, branch.id):
            raise BusinessRuleError(
                detail="O'qituvchi boshqa filialda ishlaydi.", code="teacher_branch_mismatch"
            )
        return teacher
