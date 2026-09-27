from django.contrib import admin

from .models import Debt, Discount, Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "student", "amount", "method", "payment_type", "status",
                    "period_month", "paid_at", "received_by")
    list_filter = ("method", "payment_type", "status", "branch", "period_month")
    search_fields = ("student__first_name", "student__last_name", "receipt_no")


@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ("student", "period_month", "amount_due", "amount_paid", "due_date", "status")
    list_filter = ("status", "period_month", "student__branch")
    search_fields = ("student__first_name", "student__last_name")
    actions = ["mark_paid"]

    @admin.action(description="Belgilangan qarzlarni 'to'landi' deb belgilash")
    def mark_paid(self, request, queryset):
        queryset.update(status="paid")


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ("name", "discount_type", "value", "branch", "course", "is_auto_apply", "is_active")
    list_filter = ("discount_type", "is_auto_apply", "is_active")
    search_fields = ("name", "code")
