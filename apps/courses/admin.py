from django.contrib import admin

from .models import Course, CourseLevel


class CourseLevelInline(admin.TabularInline):
    model = CourseLevel
    extra = 0
    fields = ("name", "code", "price", "duration_months", "ordering", "is_active")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "base_price", "duration_months", "is_featured", "is_active")
    list_filter = ("category", "is_active", "is_featured")
    search_fields = ("name", "description")
    inlines = (CourseLevelInline,)


@admin.register(CourseLevel)
class CourseLevelAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "price", "ordering", "is_active")
    list_filter = ("course", "is_active")
    search_fields = ("name", "course__name")
