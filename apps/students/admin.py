from django.contrib import admin

from .models import Enrollment, Student


class EnrollmentInline(admin.TabularInline):
    model = Enrollment
    extra = 0
    fields = ("group", "status", "start_date", "monthly_fee", "discount_percent", "is_active")


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("full_name", "branch", "phone", "status", "start_date", "is_active")
    list_filter = ("branch", "status", "is_active")
    search_fields = ("first_name", "last_name", "phone", "telegram_id")
    filter_horizontal = ("parents",)
    inlines = (EnrollmentInline,)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "group", "status", "start_date", "end_date", "final_fee", "is_active")
    list_filter = ("status", "is_active", "group__branch")
    search_fields = ("student__first_name", "student__last_name", "group__name")
