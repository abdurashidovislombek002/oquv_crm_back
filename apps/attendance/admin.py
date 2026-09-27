from django.contrib import admin

from .models import AttendanceRecord, Lesson


class AttendanceRecordInline(admin.TabularInline):
    model = AttendanceRecord
    extra = 0
    fields = ("student", "status", "minutes_late", "note")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("group", "date", "start_time", "teacher", "status", "is_active")
    list_filter = ("branch", "status", "date")
    search_fields = ("group__name", "topic", "teacher__first_name")
    inlines = (AttendanceRecordInline,)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("lesson", "student", "status", "minutes_late", "marked_at")
    list_filter = ("status", "lesson__branch")
    search_fields = ("student__first_name", "student__last_name")
