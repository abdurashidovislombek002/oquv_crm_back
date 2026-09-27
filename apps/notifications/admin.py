from django.contrib import admin

from .models import Notification, NotificationTemplate


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "channel", "is_active")
    list_filter = ("channel", "is_active")
    search_fields = ("key", "name", "body")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("subject", "channel", "status", "recipient", "student", "scheduled_at",
                    "sent_at", "attempts")
    list_filter = ("channel", "status", "priority")
    search_fields = ("subject", "body", "phone", "email")
