"""Routes under /api/admin/booking/."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .admin_api import BookingAdminViewSet, BookingSettingsView, CalendarCheckView, MeetingTypeAdminViewSet

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("meeting-types", MeetingTypeAdminViewSet, basename="admin-meeting-types")
router.register("bookings", BookingAdminViewSet, basename="admin-bookings")

urlpatterns = [
    path("settings/", BookingSettingsView.as_view(), name="admin-booking-settings"),
    path("calendars/check/", CalendarCheckView.as_view(), name="admin-booking-calendars-check"),
    path("", include(router.urls)),
]
