"""API v1 root router — every app registers its viewsets here."""
from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    MyProfileView,
    UserActivityViewSet,
    UserViewSet,
)
from apps.analytics.views import DashboardViewSet
from apps.attendance.views import AttendanceRecordViewSet, LessonViewSet
from apps.branches.views import BranchViewSet, RoomViewSet
from apps.courses.views import CourseLevelViewSet, CourseViewSet
from apps.crm_leads.views import (
    LeadCallViewSet,
    LeadFollowUpViewSet,
    LeadNoteViewSet,
    LeadStatusHistoryViewSet,
    LeadViewSet,
)
from apps.groups.views import GroupViewSet
from apps.notifications.views import NotificationTemplateViewSet, NotificationViewSet
from apps.payments.views import DebtViewSet, DiscountViewSet, PaymentViewSet
from apps.students.views import EnrollmentViewSet, StudentViewSet

router = DefaultRouter()

# accounts
router.register("users", UserViewSet, basename="user")
router.register("user-activities", UserActivityViewSet, basename="user-activity")

# branches
router.register("branches", BranchViewSet, basename="branch")
router.register("rooms", RoomViewSet, basename="room")

# CRM
router.register("leads", LeadViewSet, basename="lead")
router.register("lead-notes", LeadNoteViewSet, basename="lead-note")
router.register("lead-calls", LeadCallViewSet, basename="lead-call")
router.register("lead-follow-ups", LeadFollowUpViewSet, basename="lead-follow-up")
router.register("lead-status-history", LeadStatusHistoryViewSet, basename="lead-status-history")

# catalog
router.register("courses", CourseViewSet, basename="course")
router.register("course-levels", CourseLevelViewSet, basename="course-level")

# groups
router.register("groups", GroupViewSet, basename="group")

# students
router.register("students", StudentViewSet, basename="student")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")

# attendance
router.register("lessons", LessonViewSet, basename="lesson")
router.register("attendance", AttendanceRecordViewSet, basename="attendance")

# payments
router.register("payments", PaymentViewSet, basename="payment")
router.register("debts", DebtViewSet, basename="debt")
router.register("discounts", DiscountViewSet, basename="discount")

# notifications
router.register("notifications", NotificationViewSet, basename="notification")
router.register("notification-templates", NotificationTemplateViewSet,
                basename="notification-template")

# analytics
router.register("dashboard", DashboardViewSet, basename="dashboard")

# ``config/urls.py`` does: path("api/v1/", include("config.api.router"))
urlpatterns = [
    path("profile/", MyProfileView.as_view(), name="profile"),
    path("", include(router.urls)