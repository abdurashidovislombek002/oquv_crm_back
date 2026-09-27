"""Filters for the user directory."""
from __future__ import annotations

import django_filters as filters

from common.filters import BaseFilterSet

from .constants import Role
from .models import User, UserActivity


class UserFilter(BaseFilterSet):
    role = filters.ChoiceFilter(field_name="role", choices=Role.choices)
    branch = filters.NumberFilter(field_name="branch_id")
    username = filters.CharFilter(field_name="username", lookup_expr="iexact")
    phone = filters.CharFilter(field_name="phone", lookup_expr="icontains")
    telegram_id = filters.CharFilter(field_name="telegram_id", lookup_expr="icontains")
    is_staff = filters.BooleanFilter(field_name="is_staff")
    is_superuser = filters.BooleanFilter(field_name="is_superuser")

    class Meta:
        model = User
        fields = ("role", "branch", "is_active", "is_staff", "is_superuser")


class UserActivityFilter(BaseFilterSet):
    user = filters.NumberFilter(field_name="user_id")
    action = filters.CharFilter(field_name="action")

    class Meta:
        model = UserActivity
        fields = ("user", "action")
