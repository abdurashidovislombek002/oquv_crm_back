from django.contrib import admin

from .models import Group, GroupSchedule


class GroupScheduleInline(admin.TabularInline):
    model = GroupSchedule
    extra = 0
    fields = ("day_of_week", "start_time", "end_time", "room", "is_active_slot")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "course", "level", "status", "capacity", "start_date", "is_active")
    list_filter = ("branch", "course", "status", "is_active")
    search_fields = ("name", "code", "course__name")
    filter_horizontal = ("teachers",)
    inlines = (GroupScheduleInline,)


@admin.register(GroupSchedule)
class GroupScheduleAdmin(admin.ModelAdmin):
    list_display = ("group", "day_of_week", "start_time", "end_time", "room")
    list_filter = ("day_of_week", "room__branch")
