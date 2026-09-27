"""Views for payments, debts and discounts."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.students.models import Student
from common.pagination import CompactPagination
from common.permissions import IsManagerOrAbove
from common.views import BaseModelViewSet, BaseReadOnlyViewSet

from .filters import DebtFilter, DiscountFilter, PaymentFilter
from .models import Debt, Discount, Payment
from .serializers import (
    DebtSerializer,
    DebtSummarySerializer,
    DebtWriteSerializer,
    DebtsSummarySerializer,
    DiscountSerializer,
    PaymentCreateSerializer,
    PaymentListSerializer,
    PaymentRefundSerializer,
    PaymentSerializer,
)
from .services import DebtService, DiscountService, PaymentService


class PaymentViewSet(BaseModelViewSet):
    """``/api/v1/payments/``"""

    queryset = Payment.active.all()
    serializer_class = PaymentSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("student__first_name", "student__last_name", "receipt_no", "note")
    ordering_fields = ("paid_at", "amount", "period_month", "created_at")
    ordering = ("-paid_at",)
    filterset_class = PaymentFilter
    pagination_class = CompactPagination
    serializer_class_map = {
        "list": PaymentListSerializer,
        "retrieve": PaymentSerializer,
        "create": PaymentCreateSerializer,
        "history": PaymentListSerializer,
    }

    def get_queryset(self):
        return super().get_queryset().with_related()

    def get_permissions(self):
        if self.action in ("list", "retrieve", "history", "student_history", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def create(self, request, *args, **kwargs):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = PaymentService.create_payment(serializer.validated_data, actor=request.user)
        return Response(PaymentSerializer(payment).data, status=201)

    def perform_destroy(self, instance) -> None:
        """Payments are never deleted — only cancelled (audit trail)."""
        from common.exceptions import BusinessRuleError

        raise BusinessRuleError(
            detail="To'lovni o'chirib bo'lmaydi, faqat bekor qilish (cancel) mumkin.",
            code="payment_immutable",
        )

    @extend_schema(request=PaymentRefundSerializer, responses=PaymentSerializer)
    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        payment = self.get_object()
        serializer = PaymentRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = PaymentService.refund(
            payment, serializer.validated_data["amount"],
            actor=request.user, note=serializer.validated_data.get("note", ""),
        )
        return Response(PaymentSerializer(refund).data, status=201)

    @extend_schema(responses=PaymentListSerializer(many=True), description="O'quvchi to'lov tarixi")
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        student = self.get_object().student
        payments = PaymentService.history(
            student,
            period_from=_parse_date(request.query_params.get("period_from")),
            period_to=_parse_date(request.query_params.get("period_to")),
        )
        return Response(PaymentListSerializer(payments, many=True).data)

    @extend_schema(responses=PaymentListSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="student-history")
    def student_history(self, request):
        student_id = request.query_params.get("student_id")
        if not student_id:
            from common.exceptions import BusinessRuleError

            raise BusinessRuleError(detail="student_id majburiy.", code="student_required")
        student = Student.objects.filter(pk=student_id).first()
        if student is None:
            from common.exceptions import NotFoundError

            raise NotFoundError(detail="O'quvchi topilmadi.")
        payments = PaymentService.history(student)
        return Response(PaymentListSerializer(payments, many=True).data)

    @extend_schema(responses=None, description="Davr bo'yicha to'lovlar hisoboti")
    @action(detail=False, methods=["get"], url_path="report")
    def report(self, request):
        year = request.query_params.get("year")
        month = request.query_params.get("month")
        data = PaymentService.period_report(
            branch_id=request.query_params.get("branch_id"),
            year=int(year) if year else None,
            month=int(month) if month else None,
        )
        return Response(data)


class DebtViewSet(BaseReadOnlyViewSet):
    """``/api/v1/debts/`` — monthly obligations."""

    queryset = Debt.active.select_related("student", "enrollment", "enrollment__group").all()
    serializer_class = DebtSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("student__first_name", "student__last_name", "student__phone")
    ordering_fields = ("period_month", "due_date", "status", "amount_due")
    ordering = ("-period_month",)
    filterset_class = DebtFilter
    pagination_class = CompactPagination

    @extend_schema(request=None, responses=DebtsSummarySerializer, description="Umumiy qarz holati")
    @action(detail=False, methods=["get"])
    def summary(self, request):
        branch_id = request.query_params.get("branch_id")
        queryset = self.get_queryset()
        if branch_id:
            queryset = queryset.filter(student__branch_id=branch_id)
        debtors = DebtService.debtors(branch_id=branch_id)
        return Response(
            {
                "total_debt": queryset.aggregate(total=Sum("amount_due") - Sum("amount_paid"))["total"] or 0,
                "students_count": queryset.values("student_id").distinct().count(),
                "overdue_count": queryset.filter(status="overdue").count(),
                "debtors": debtors[:100],
            }
        )

    @extend_schema(request=DebtWriteSerializer, responses=None,
                   description="O'quvchi uchun oylik qarz hisobini qayta hisoblash")
    @action(detail=False, methods=["post"], url_path="recalculate")
    def recalculate(self, request):
        serializer = DebtWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student_id = request.query_params.get("student_id")
        if student_id:
            student = Student.objects.filter(pk=student_id).first()
            if student is None:
                from common.exceptions import NotFoundError

                raise NotFoundError(detail="O'quvchi topilmadi.")
            debts = DebtService.generate_for_student(
                student,
                months_back=serializer.validated_data.get("months_back", 0),
                months_forward=serializer.validated_data.get("months_forward", 0),
            )
            return Response({"created": len(debts)})
        count = DebtService.generate_for_branch(
            serializer.validated_data.get("branch"),
            months_forward=serializer.validated_data.get("months_forward", 0),
        )
        return Response({"students_processed": count})

    @extend_schema(request=None, responses=None, description="Muddati o'tgan qarzlarni belgilash")
    @action(detail=False, methods=["post"], url_path="refresh-overdue")
    def refresh_overdue(self, request):
        updated = DebtService.refresh_overdue(branch_id=request.query_params.get("branch_id"))
        return Response({"updated": updated})

    @extend_schema(request=None, responses=DebtSerializer, description="Qarzni kechirish")
    @action(detail=True, methods=["post"])
    def waive(self, request, pk=None):
        debt = DebtService.waive(self.get_object(), note=request.data.get("note", ""))
        return Response(DebtSerializer(debt).data)

    @extend_schema(responses=DebtSummarySerializer, description="O'quvchi balansi")
    @action(detail=True, methods=["get"], url_path="student-summary")
    def student_summary(self, request, pk=None):
        return Response(DebtService.student_summary(self.get_object().student))


class DiscountViewSet(BaseModelViewSet):
    """``/api/v1/discounts/``"""

    queryset = Discount.active.all()
    serializer_class = DiscountSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ("name", "code", "description")
    ordering_fields = ("name", "value", "created_at")
    ordering = ("-created_at",)
    filterset_class = DiscountFilter
    pagination_class = CompactPagination

    def get_permissions(self):
        if self.action in ("list", "retrieve", "options"):
            return [IsAuthenticated()]
        return [IsManagerOrAbove()]

    def perform_create(self, serializer) -> None:
        serializer.instance = DiscountService.create_discount(serializer.validated_data)

    @extend_schema(responses=None, description="Joriy oy uchun avtomatik chegirmalar")
    @action(detail=False, methods=["get"], url_path="auto-applicable")
    def auto_applicable(self, request):
        discount = DiscountService.auto_applicable(
            branch=request.query_params.get("branch_id"),
            course=request.query_params.get("course_id"),
        )
        return Response(DiscountSerializer(discount).data if discount else None)


def _parse_date(value):
    if not value:
        return None
    from django.utils.dateparse import parse_date

    return parse_date(value)
