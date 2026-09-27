"""Attendance business logic: lesson generation, marking and statistics."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.groups.models import Group, GroupSchedule
from apps.students.models import Enrollment, EnrollmentStatus
from common.exceptions import BusinessRuleError, NotFoundError
from common.services import BaseService
from common.utils import next_weekday

from .models import AttendanceRecord, AttendanceStatus, Lesson, LessonStatus


class LessonService(BaseService):
    model = Lesson

    @classmethod
    @transaction.atomic
    def create_lesson(cls, data: Dict[str, Any], *, actor: Optional[User] = None,
                      generate_records: bool = True) -> Lesson:
        payload = cls.cleanup(data)
        group = payload.get("group") or Group.objects.filter(pk=payload.get("group_id")).first()
        if group is None:
            raise BusinessRuleError(detail="Guruh tanlash majburiy.", code="group_required")
        lesson_date = payload.get("date") or timezone.localdate()
        slot = payload.get("schedule_slot")
        slot = slot if isinstance(slot, GroupSchedule) else None

        start_time = payload.get("start_time") or (slot.start_time if slot else group.start_time)
        end_time = payload.get("end_time") or (slot.end_time if slot else group.end_time)

        if Lesson.base_queryset().filter(
            group=group, date=lesson_date, start_time=start_time
        ).exists():
            raise BusinessRuleError(
                detail="Bu guruh uchun shu vaqtda dars allaqachon yaratilgan.", code="duplicate_lesson"
            )

        lesson = Lesson(
            group=group,
            branch=payload.get("branch") or group.branch,
            date=lesson_date,
            start_time=start_time,
            end_time=end_time,
            room=payload.get("room") or (slot.room if slot else group.room),
            teacher=payload.get("teacher") or group.head_teacher or group.teachers.first(),
            topic=payload.get("topic", ""),
            homework=payload.get("homework", ""),
            is_generated=bool(payload.get("is_generated", False)),
            created_by=actor,
        )
        lesson.full_clean(exclude=["created_by"])
        lesson.save()

        if generate_records:
            AttendanceService.generate_records(lesson, actor=actor)
        return lesson

    @classmethod
    def update_lesson(cls, instance: Lesson, data: Dict[str, Any]) -> Lesson:
        payload = cls.cleanup(data)
        for field, value in payload.items():
            setattr(instance, field, value)
        instance.full_clean(exclude=["created_by"])
        instance.save()
        return instance

    @classmethod
    def generate_lessons_from_schedule(cls, group: Group, *, from_date: date, to_date: date,
                                       actor: Optional[User] = None) -> List[Lesson]:
        """Creates lessons for a date range from the group's weekly schedule."""
        if to_date < from_date:
            raise BusinessRuleError(
                detail="Tugash sanasi boshlanishdan oldin bo'lmasligi kerak.", code="invalid_range"
            )
        if (to_date - from_date).days > 120:
            raise BusinessRuleError(
                detail="Bir vaqtda ko'pi bilan 120 kunlik jadval yaratiladi.", code="range_too_big"
            )
        slots = list(group.schedule.filter(is_active=True))
        if not slots:
            raise BusinessRuleError(
                detail="Guruhda jadval (haftaning kunlari) belgilanmagan.", code="no_schedule"
            )
        created: List[Lesson] = []
        with cls.atomic():
            current = from_date
            while current <= to_date:
                for slot in slots:
                    if cls._iso_weekday(current) != slot.day_of_week:
                        continue
                    if current < (group.start_date or current):
                        continue
                    if group.end_date and current > group.end_date:
                        continue
                    lesson, created_flag = Lesson.objects.get_or_create(
                        group=group,
                        date=current,
                        start_time=slot.start_time,
                        defaults={
                            "branch": group.branch,
                            "end_time": slot.end_time,
                            "room": slot.room or group.room,
                            "teacher": group.head_teacher or group.teachers.first(),
                            "is_generated": True,
                            "created_by": actor,
                        },
                    )
                    if created_flag:
                        AttendanceService.generate_records(lesson, actor=actor)
                        created.append(lesson)
                current += timedelta(days=1)
        return created

    @classmethod
    def today_lessons(cls, branch_id: Optional[int] = None) -> List[Lesson]:
        queryset = Lesson.active.filter(date=timezone.localdate())
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        return list(queryset.with_related())

    @staticmethod
    def _iso_weekday(value: date) -> int:
        return value.weekday() + 1


class AttendanceService(BaseService):
    model = AttendanceRecord

    @classmethod
    @transaction.atomic
    def generate_records(cls, lesson: Lesson, *, actor: Optional[User] = None) -> List[AttendanceRecord]:
        """Creates an ``ABSENT`` record for every active enrollment of the group."""
        enrollments = Enrollment.active.filter(
            group=lesson.group, is_active=True, status=EnrollmentStatus.ACTIVE
        ).select_related("student")
        records: List[AttendanceRecord] = []
        existing = set(
            AttendanceRecord.objects.filter(lesson=lesson).values_list("student_id", flat=True)
        )
        for enrollment in enrollments:
            if enrollment.student_id in existing:
                continue
            records.append(
                AttendanceRecord(
                    lesson=lesson,
                    student=enrollment.student,
                    status=AttendanceStatus.ABSENT,
                    marked_by=actor,
                )
            )
        if records:
            AttendanceRecord.objects.bulk_create(records)
        return records

    @classmethod
    def mark(cls, lesson: Lesson, student_id: int, status: str, *, actor: Optional[User] = None,
             note: str = "", minutes_late: int = 0) -> AttendanceRecord:
        if status not in AttendanceStatus.values:
            raise BusinessRuleError(detail=f"Noma'lum holat: {status}", code="invalid_status")
        if not cls._is_enrolled(lesson, student_id):
            raise BusinessRuleError(
                detail="O'quvchi bu guruhga biriktirilmagan.", code="not_enrolled"
            )
        record, _ = AttendanceRecord.objects.get_or_create(
            lesson=lesson,
            student_id=student_id,
            defaults={"status": status, "note": note, "marked_by": actor},
        )
        record.status = status
        record.note = note or record.note
        record.minutes_late = minutes_late
        record.marked_by = actor
        record.marked_at = timezone.now()
        record.is_active = True
        record.save()
        if lesson.status == LessonStatus.SCHEDULED:
            lesson.status = LessonStatus.HELD
            lesson.save(update_fields=["status", "updated_at"])
        return record

    @classmethod
    def bulk_mark(cls, lesson: Lesson, data: Iterable[Dict[str, Any]],
                  *, actor: Optional[User] = None) -> List[AttendanceRecord]:
        records: List[AttendanceRecord] = []
        with cls.atomic():
            for item in data:
                records.append(
                    cls.mark(
                        lesson,
                        int(item["student_id"]),
                        item.get("status", AttendanceStatus.PRESENT),
                        actor=actor,
                        note=item.get("note", ""),
                        minutes_late=int(item.get("minutes_late", 0) or 0),
                    )
                )
        return records

    @classmethod
    def mark_all_present(cls, lesson: Lesson, *, actor: Optional[User] = None) -> List[AttendanceRecord]:
        student_ids = list(
            AttendanceRecord.objects.filter(lesson=lesson).values_list("student_id", flat=True)
        )
        return cls.bulk_mark(
            lesson,
            [{"student_id": sid, "status": AttendanceStatus.PRESENT} for sid in student_ids],
            actor=actor,
        )

    @classmethod
    def student_summary(cls, student, *, date_from: Optional[date] = None,
                        date_to: Optional[date] = None) -> Dict[str, Any]:
        queryset = AttendanceRecord.active.filter(student=student)
        if date_from:
            queryset = queryset.filter(lesson__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(lesson__date__lte=date_to)
        counts = dict(
            queryset.values_list("status").annotate(total=Count("id"))
        )
        total = sum(counts.values())
        attended = counts.get(AttendanceStatus.PRESENT, 0) + counts.get(AttendanceStatus.ONLINE, 0)
        return {
            "student": student.full_name,
            "total_lessons": total,
            "present": counts.get(AttendanceStatus.PRESENT, 0),
            "absent": counts.get(AttendanceStatus.ABSENT, 0),
            "late": counts.get(AttendanceStatus.LATE, 0),
            "excused": counts.get(AttendanceStatus.EXCUSED, 0),
            "online": counts.get(AttendanceStatus.ONLINE, 0),
            "attendance_rate": round(attended / total * 100, 2) if total else 0.0,
        }

    @classmethod
    def group_summary(cls, group: Group, *, date_from: Optional[date] = None,
                      date_to: Optional[date] = None) -> Dict[str, Any]:
        queryset = AttendanceRecord.active.filter(lesson__group=group)
        if date_from:
            queryset = queryset.filter(lesson__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(lesson__date__lte=date_to)
        counts = dict(queryset.values_list("status").annotate(total=Count("id")))
        total = sum(counts.values())
        attended = counts.get(AttendanceStatus.PRESENT, 0) + counts.get(AttendanceStatus.ONLINE, 0)
        per_student = cls._per_student(queryset)
        return {
            "group": group.name,
            "total_lessons": queryset.values("lesson_id").distinct().count(),
            "total_records": total,
            "present": counts.get(AttendanceStatus.PRESENT, 0),
            "absent": counts.get(AttendanceStatus.ABSENT, 0),
            "late": counts.get(AttendanceStatus.LATE, 0),
            "excused": counts.get(AttendanceStatus.EXCUSED, 0),
            "attendance_rate": round(attended / total * 100, 2) if total else 0.0,
            "students": per_student,
        }

    @classmethod
    def daily_report(cls, *, day: Optional[date] = None, branch_id: Optional[int] = None) -> Dict[str, Any]:
        day = day or timezone.localdate()
        lessons = Lesson.active.filter(date=day, status=LessonStatus.HELD)
        if branch_id:
            lessons = lessons.filter(branch_id=branch_id)
        records = AttendanceRecord.active.filter(lesson__in=lessons)
        counts = dict(records.values_list("status").annotate(total=Count("id")))
        total = sum(counts.values())
        attended = counts.get(AttendanceStatus.PRESENT, 0) + counts.get(AttendanceStatus.ONLINE, 0)
        return {
            "date": day,
            "lessons_count": lessons.count(),
            "lessons_without_marks": lessons.filter(records__isnull=True).count(),
            "present": counts.get(AttendanceStatus.PRESENT, 0),
            "absent": counts.get(AttendanceStatus.ABSENT, 0),
            "late": counts.get(AttendanceStatus.LATE, 0),
            "excused": counts.get(AttendanceStatus.EXCUSED, 0),
            "online": counts.get(AttendanceStatus.ONLINE, 0),
            "attendance_rate": round(attended / total * 100, 2) if total else 0.0,
        }

    @classmethod
    def close_past_lessons(cls, *, days: int = 0) -> int:
        """Celery task: mark old scheduled lessons as held."""
        cutoff = timezone.localdate() - timedelta(days=days)
        return cls.model.objects.filter(
            status=LessonStatus.SCHEDULED, date__lte=cutoff
        ).update(status=LessonStatus.HELD)

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _is_enrolled(lesson: Lesson, student_id: int) -> bool:
        return Enrollment.active.filter(
            group=lesson.group, student_id=student_id, is_active=True
        ).exists()

    @staticmethod
    def _per_student(queryset) -> List[Dict[str, Any]]:
        rows = (
            queryset.values("student_id", "student__first_name", "student__last_name", "status")
            .annotate(total=Count("id"))
        )
        summary: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            entry = summary.setdefault(
                row["student_id"],
                {
                    "student_id": row["student_id"],
                    "name": f"{row['student__first_name']} {row['student__last_name']}".strip(),
                    "present": 0, "absent": 0, "late": 0, "excused": 0, "online": 0, "total": 0,
                },
            )
            entry[row["status"]] = entry.get(row["status"], 0) + row["total"]
            entry["total"] += row["total"]
        result = []
        for entry in summary.values():
            attended = entry["present"] + entry["online"]
            entry["attendance_rate"] = round(attended / entry["total"] * 100, 2) if entry["total"] else 0.0
            result.append(entry)
        return sorted(result, key=lambda item: item["name"])
