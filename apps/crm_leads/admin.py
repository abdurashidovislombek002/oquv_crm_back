from django.contrib import admin

from .models import Lead, LeadCall, LeadFollowUp, LeadNote, LeadStatusHistory


class LeadStatusHistoryInline(admin.TabularInline):
    model = LeadStatusHistory
    extra = 0
    fields = ("from_status", "to_status", "comment", "changed_by", "changed_at")
    readonly_fields = ("from_status", "to_status", "comment", "changed_by", "changed_at")
    can_delete = False


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "branch", "status", "source", "assigned_to",
                    "next_follow_up_at", "is_active")
    list_filter = ("branch", "status", "source", "priority", "is_active")
    search_fields = ("full_name", "phone", "email", "telegram_id")
    inlines = (LeadStatusHistoryInline,)


@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    list_display = ("lead", "author", "is_pinned", "created_at")
    search_fields = ("text", "lead__full_name")


@admin.register(LeadCall)
class LeadCallAdmin(admin.ModelAdmin):
    list_display = ("lead", "caller", "direction", "result", "called_at")
    list_filter = ("result", "direction")


@admin.register(LeadFollowUp)
class LeadFollowUpAdmin(admin.ModelAdmin):
    list_display = ("lead", "assigned_to", "due_at", "status")
    list_filter = ("status",)
