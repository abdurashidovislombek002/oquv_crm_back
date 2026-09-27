"""Student and enrollment business logic."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.constants import Role
from apps.accounts.models import User
from apps.groups.models import Group
from apps.groups.services import GroupService
from common.exceptions import BusinessRuleError, NotFoundError
from common.services import BaseService
from common.utils import add_months, format_phone, month_start

from .models import Enrollment, EnrollmentStatus, Student, StudentStatus


class StudentService(BaseService):
    model = Student

    @classmethod
    @transaction.atomic
    def create_student(cls, data: Dict[str, Any], *, actor: Optional[User] = None) -> Student:
        payload = cls.cleanup(data)
        portal = payload.pop("portal_account", None) or {}
        parents = payload.pop("parents", None)
        create_user = bool(payload.pop("create_portal_account", False))

        if not payload.get("first_name") or not payload.get("last_name"):
            raise BusinessRuleError(
                detail="Ism va familiya majburiy.", code="name_required"
            )
        branch = payload.get("branch") or (actor.branch if actor else None)
        if branch is None:
            raise BusinessRuleError(detail="Filial tanlash majburiy.", code="branch_required")
        payload["branch"] = branch

        student = Student(**payload, created_by=actor)
        student.full_clean(exclude=["created_by"])
        student.save()

        if parents:
            student.parents.set(cls._validate_parents(parents, branch))
        if create_user or portal:
            cls.attach_portal_account(student, portal, actor=actor)
        return student

    @classmethod
    def update_student(cls, instance: Student, data: Dict[str, Any], *, actor: Optional[User] = None) -> Student:
        payload = cls.cleanup(data)
        parents = payload.pop("parents", None)
        portal = payload.pop("portal_account", None)
        for field, value in payload.items():
            setattr(instance, field, value)
        instance.full_clean(exclude=["created_by"])
        instance.save()
        if parents is not None:
            instance.parents.set(cls._validate_parents(parents, instance.branch))
        if portal:
            cls.attach_portal_account(instance, portal, actor=actor)
        return instance

    @classmethod
    def attach_portal_account(cls, student: Student, data: Dict[str, Any], *, actor: Optional[User] = None) -> User:
        """Creates (or links) a ``role=student`` portal account."""
        from apps.accounts.services import UserService

        data = cls.cleanup(data)
        if student.user_id:
            return student.user
        username = data.get("username") or f"student{student.pk}"
        password = data.get("password") or User.objects.make_random_password()
        user = UserService.create_user(
            {
                "username": username,
                "email": data.get("email") or student.email,
                "password": password,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "role": Role.STUDENT,
                "branch": student.branch,
                "phone": data.get("phone") or student.phone,
            },
            actor=actor,
        )
        student.user = user
        student.save(update_fields=["user", "updated_at"])
        return user

    @classmethod
    def set_status(cls, instance: Student, status: str, *, reason: str = "") -> Student:
        if status not in StudentStatus.values:
            raise BusinessRuleError(detail=f"Noma'lum holat: {status}", code="invalid_status")
        instance.status = status
        if status == StudentStatus.GRADUATED:
            instance.finish_date = timezone.localdate()
        fields = ["status", "updated_at", "finish_date"] if status == StudentStatus.GRADUATED \
            else ["status", "updated_at"]
        instance.save(update_fields=fields)

        enrollment_status = {
            StudentStatus.GRADUATED: EnrollmentStatus.COMPLETED,
            StudentStatus.EXPELLED: EnrollmentStatus.LEFT,
            StudentStatus.FROZEN: EnrollmentStatus.PAUSED,
        }.get(status)
        if enrollment_status:
            instance.enrollments.filter(
                status=EnrollmentStatus.ACTIVE
            ).update(status=enrollment_status)
        if reason:
            instance.notes = f"{instance.notes}\n[{status}] {reason}".strip()
            instance.save(update_fields=["notes", "updated_at"])
        return instance

    @classmethod
    def delete_student(cls, instance: Student) -> None:
        if instance.debts.filter(status__in=["unpaid", "partial", "overdue"]).exists():
            raise BusinessRuleError(
                detail="O'quvchining qarzi bor, avval to'lovni amalga oshiring.", code="student_has_debt"
            )
        for enrollment in instance.enrollments.filter(is_active=True):
            enrollment.status = EnrollmentStatus.LEFT
            enrollment.is_active = False
            enrollment.save(update_fields=["status", "is_active", "updated_at"])
        instance.soft_delete()

    @classmethod
    def find_duplicate(cls, phone: str, last_name: str = "") -> Optional[Student]:
        if not phone:
            return None
        queryset = Student.base_queryset().filter(phone=format_phone(phone))
        if last_name:
            queryset = queryset.filter(last_name__iexact=last_name)
        return queryset.first()

    @classmethod
    def children_of(cls, parent: User) -> List[Student]:
        return list(Student.objects.filter(parents=parent).distinct())

    @staticmethod
    def _validate_parents(parents: Any, branch: Any) -> List[User]:
        resolved: List[User] = []
        for parent in parents:
            if not isinstance(parent, User):
                parent = User.objects.filter(pk=parent).first()
            if parent is None:
                raise NotFoundError(detail="Ota-ona topilmadi.")
            if parent.role != Role.PARENT and not parent.is_superuser:
                raise BusinessRuleError(
                    detail=f"{parent} ota-ona roliga ega emas.", code="invalid_parent_role"
                )
            resolved.append(parent)
        return resolved


class EnrollmentService(BaseService):
    model = Enrollment

    @classmethod
    @transaction.atomic
    def enroll(cls, data: Dict[str, Any], *, actor: Optional[User] = None) -> Enrollment:
        payload = cls.cleanup(data)
        student = payload.get("student")
        group = payload.get("group")
        if student is None or group is None:
            raise BusinessRuleError(
                detail="O'quvchi va guruh tanlash majburiy.", code="student_group_required"
            )
        if isinstance(student, int):
            student = Student.objects.filter(pk=student).first()
        if isinstance(group, int):
            group = Group.objects.filter(pk=group).first()
        if student is None or group is None:
            raise NotFoundError(detail="O'quvchi yoki guruh topilmadi.")
        if not student.is_active:
            raise BusinessRuleError(detail="O'quvchi arxivdan chiqarilgan.", code="student_inactive")
        if student.branch_id != group.branch_id:
            raise BusinessRuleError(
                detail="O'quvchi va guruh turli filiallarga tegishli.", code="branch_mismatch"
            )
        if cls.base_queryset().filter(
            student=student, group=group, is_active=True
        ).exists():
            raise BusinessRuleError(
                detail="O'quvchi bu guruhda allaqachon o'qiyapti.", code="already_enrolled"
            )
        GroupService.assert_can_enroll(group)

        start_date = payload.get("start_date") or timezone.localdate()
        enrollment = Enrollment(
            **{**payload, "student": student, "group": group, "start_date": start_date,
               "created_by": actor},
        )
        enrollment.full_clean(exclude=["created_by"])
        enrollment.save()

        if student.status == StudentStatus.TRIAL:
            student.status = StudentStatus.ACTIVE
            student.save(update_fields=["status", "updated_at"])
        return enrollment

    @classmethod
    def change_group(cls, instance: Enrollment, new_group: Group, *, actor: Optional[User] = None,
                     end_date: Optional[date] = None) -> Enrollment:
        if new_group.pk == instance.group_id:
            raise BusinessRuleError(detail="Yangi guruh oldingisiga teng.", code="same_group")
        if new_group.branch_id != instance.student.branch_id:
            raise BusinessRuleError(
                detail="O'quvchi va guruh turli filiallarga tegishli.", code="branch_mismatch"
            )
        GroupService.assert_can_enroll(new_group)
        with cls.atomic():
            instance.status = EnrollmentStatus.MOVED
            instance.is_active = False
            instance.end_date = end_date or timezone.localdate()
            instance.save(update_fields=["status", "is_active", "end_date", "updated_at"])
            moved = Enrollment.objects.create(
                student=instance.student,
                group=new_group,
                start_date=timezone.localdate(),
                monthly_fee=instance.monthly_fee,
                discount_percent=instance.discount_percent,
                discount=instance.discount,
                created_by=actor or instance.created_by,
            )
        return moved

    @classmethod
    def pause(cls, instance: Enrollment, *, resume: bool = False) -> Enrollment:
        if resume:
            instance.status = EnrollmentStatus.ACTIVE
        else:
            if not instance.is_active_enrollment:
                raise BusinessRuleError(
                    detail="Faol bo'lmagan biriktirishni to'xtatib bo'lmaydi.", code="not_active"
                )
            instance.status = EnrollmentStatus.PAUSED
        instance.save(update_fields=["status", "updated_at"])
        return instance

    @classmethod
    def unenroll(cls, instance: Enrollment, *, reason: str = "", end_date: Optional[date] = None) -> Enrollment:
        instance.status = EnrollmentStatus.LEFT
        instance.is_active = False
        instance.end_date = end_date or timezone.localdate()
        if reason:
            instance.notes = f"{instance.notes}\n[ketish] {reason}".strip()
        instance.save(update_fields=["status", "is_active", "end_date", "notes", "updated_at"])
        return instance

    @classmethod
    def calculate_fee(cls, enrollment: Enrollment) -> Dict[str, Any]:
        base = enrollment.base_fee
        percent = enrollment.total_discount_percent
        return {
            "base_fee": base,
            "discount_percent": percent,
            "final_fee": enrollment.final_fee,
        }

    @classmethod
    def monthly_charge_for(cls, enrollment: Enrollment, period: Optional[date] = None) -> Any:
        """Fee amount that must be paid for the given month."""
        period = month_start(period or timezone.localdate())
        start_period = month_start(enrollment.start_date)
        if period < start_period:
            return enrollment.final_fee * 0
        return enrollment.final_fee
