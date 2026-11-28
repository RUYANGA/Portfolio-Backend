"""Routes under /api/booking/."""

from django.urls import path

from .api import (
    BookingView,
    CancelBookingView,
    GoogleCalendarCallbackView,
    GoogleCalendarConnectView,
    ManageBookingView,
    SlotsView,
)

urlpatterns = [
    path("", BookingView.as_view(), name="booking"),
    path("slots/", SlotsView.as_view(), name="booking-slots"),
    path("manage/<str:token>/", ManageBookingView.as_view(), name="booking-manage"),
    path("manage/<str:token>/cancel/", CancelBookingView.as_view(), name="booking-cancel"),
    path("manage/<str:token>/google/connect/", GoogleCalendarConnectView.as_view(), name="booking-google-connect"),
    path("google/callback/", GoogleCalendarCallbackView.as_view(), name="booking-google-callback"),
]
