"""Serializers for payments, debts and discounts."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from rest_framework import serializers

from apps.accounts.serializers import UserListSerializer
from apps.branches.models import Branch
from apps.students.models import Enrollment, Student

from .models import Debt, DebtStatus, Discount, Payment, PaymentMethod, PaymentStatus, PaymentType


class PaymentListSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    period_label = serializers.CharField(read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id", "student", "student_name", "amount", "discount_amount", "total", "method",
            "method_display", "payment_type", "status", "period_month", "period_label",
            "paid_at", "receipt_no",
        )


class PaymentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    received_by = UserListSerializer(read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    type_display = serializers.CharField(source="get_payment_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id", "branch", "branch_name", "student", "student_name", "enrollment", "amount",
            "discount_amount", "total", "method", "method_display", "payment_type",
            "type_display", "status", "status_display", "period_month", "period_label",
            "paid_at", "receipt_no", "received_by", "note", "is_paid", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = ("receipt_no", "received_by", "created_at", "updated_at")


class PaymentCreateSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    enrollment = serializers.PrimaryKeyRelatedField(
        queryset=Enrollment.objects.all(), required=False, allow_null=True
    )
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal("0")
    )
    method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False,
                                     default=PaymentMethod.CASH)
    payment_type = serializers.ChoiceField(choices=PaymentType.choices, required=False,
                                           default=PaymentType.PAYMENT)
    status = serializers.ChoiceField(choices=PaymentStatus.choices, required=False,
                                     default=PaymentStatus.PAID)
    period_month = serializers.DateField(required=False)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True
    )
    note = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("To'lov summasi 0 dan katta bo'lishi kerak.")
        return value


class PaymentRefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    note = serializers.CharField(required=False, allow_blank=True)


class DebtSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    group_name = serializers.CharField(source="enrollment.group.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    remaining = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)

    class Meta:
        model = Debt
        fields = (
            "id", "student", "student_name", "enrollment", "group_name", "period_month",
            "amount_due", "amount_paid", "remaining", "due_date", "status", "status_display",
            "is_overdue", "days_overdue", "note", "is_active", "created_at", "updated_at",
        )
        read_only_fields = fields


class DiscountSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    course_name = serializers.CharField(source="course.name", read_only=True, default=None)

    class Meta:
        model = Discount
        fields = (
            "id", "name", "code", "discount_type", "value", "branch", "branch_name", "course",
            "course_name", "description", "valid_from", "valid_to", "is_auto_apply",
            "is_active", "created_at", "updated_at",
        )


class DebtSummarySerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    student = serializers.CharField()
    branch = serializers.CharField(allow_null=True)
    total_paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_expected = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_debt = serializers.DecimalField(max_digits=14, decimal_places=2)
    has_debt = serializers.BooleanField()
    overdue_debts_count = serializers.IntegerField()
    days_overdue = serializers.IntegerField()
    months_unpaid = serializers.IntegerField()
    last_payment_at = serializers.DateTimeField(allow_null=True)
    debts = serializers.ListField(child=serializers.DictField())


class DebtWriteSerializer(serializers.Serializer):
    months_back = serializers.IntegerField(required=False, min_value=0, max_value=24, default=0)
    months_forward = serializers.IntegerField(required=False, min_value=0, max_value=6, default=0)
    branch = serializers.IntegerField(required=False, allow_null=True)


class DebtsSummarySerializer(serializers.Serializer):
    total_debt = serializers.DecimalField(max_digits=14, decimal_places=2)
    students_count = serializers.IntegerField()
    overdue_count = serializers.IntegerField()
    debtors = serializers.ListField(child=serializers.DictField())
