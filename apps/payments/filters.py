"""Filters for payments and debts."""
from __future__ import annotations

import django_filters as filters
from django.db import models
from django.db.models import Q

from common.filters import BaseFilterSet

from .models import Debt, DebtStatus, Discount, Payment, PaymentMethod, PaymentStatus, PaymentType


class PaymentFilter(BaseFilterSet):
    student = filters.NumberFilter(field_name="student_id")
    branch = filters.NumberFilter(field_name="branch_id")
    enrollment = filters.NumberFilter(field_name="enrollment_id")
    method = filters.ChoiceFilter(field_name="method", choices=PaymentMethod.choices)
    payment_type = filters.ChoiceFilter(field_name="payment_type", choices=PaymentType.choices)
    status = filters.ChoiceFilter(field_name="status", choices=PaymentStatus.choices)
    period_from = filters.DateFilter(field_name="period_month", lookup_expr="gte")
    period_to = filters.DateFilter(field_name="period_month", lookup_expr="lte")
    paid_from = filters.DateTimeFilter(field_name="paid_at", lookup_expr="gte")
    paid_to = filters.DateTimeFilter(field_name="paid_at", lookup_expr="lte")
    min_amount = filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = filters.NumberFilter(field_name="amount", lookup_expr="lte")
    received_by = filters.NumberFilter(field_name="received_by_id")
    period = filters.NumberFilter(field_name="period_month__month")

    class Meta:
        model = Payment
        fields = ("branch", "student", "method", "payment_type", "status", "is_active")


class DebtFilter(BaseFilterSet):
    student = filters.NumberFilter(field_name="student_id")
    branch = filters.NumberFilter(field_name="student__branch_id")
    enrollment = filters.NumberFilter(field_name="enrollment_id")
    status = filters.MultipleChoiceFilter(field_name="status", choices=DebtStatus.choices)
    period_from = filters.DateFilter(field_name="period_month", lookup_expr="gte")
    period_to = filters.DateFilter(field_name="period_month", lookup_expr="lte")
    due_from = filters.DateFilter(field_name="due_date", lookup_expr="gte")
    due_to = filters.DateFilter(field_name="due_date", lookup_expr="lte")
    overdue = filters.BooleanFilter(method="filter_overdue")
    has_debt = filters.BooleanFilter(method="filter_has_debt")

    class Meta:
        model = Debt
        fields = ("status", "is_active")

    def filter_overdue(self, queryset, name, value):
        from django.utils import timezone

        if value is None:
            return queryset
        condition = Q(due_date__lt=timezone.localdate()) & Q(
            status__in=[DebtStatus.UNPAID, DebtStatus.PARTIAL]
        )
        return queryset.filter(condition) if value else queryset.exclude(condition)

    def filter_has_debt(self, queryset, name, value):
        if value is None:
            return queryset
        condition = Q(amount_paid__lt=models.F("amount_due")) & ~Q(status=DebtStatus.WAIVED)
        return queryset.filter(condition) if value else queryset.exclude(condition)


class DiscountFilter(BaseFilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    branch = filters.NumberFilter(field_name="branch_id")
    course = filters.NumberFilter(field_name="course_id")
    is_auto_apply = filters.BooleanFilter(field_name="is_auto_apply")

    class Meta:
        model = Discount
        fields = ("branch", "course", "is_auto_apply", "is_active")
