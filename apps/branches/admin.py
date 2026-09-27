from django.contrib import admin

from .models import Branch, Room


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "address", "phone", "is_head_office", "is_active")
    list_filter = ("is_active", "is_head_office")
    search_fields = ("name", "code", "address")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "room_type", "capacity", "is_active")
    list_filter = ("branch", "room_type", "is_active")
    search_fields = ("name", "code")
