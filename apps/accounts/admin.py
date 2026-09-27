from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, UserActivity


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "role", "branch", "phone", "is_active", "is_staff")
    list_filter = ("role", "branch", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "phone", "email")
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Shaxsiy ma'lumot", {"fields": ("first_name", "last_name", "middle_name", "email", "phone",
                                          "telegram_id", "birth_date", "avatar_url", "address")}),
        ("CRM", {"fields": ("role", "branch", "notes")}),
        ("Ruxsatlar", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Vaqtlar", {"fields": ("last_login", "last_login_ip", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2", "role", "branch", "phone"),
        }),
    )


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "ip_address", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("user__username", "ip_address")
