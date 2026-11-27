"""Routes: `collect` under /api/analytics/, `report` under /api/admin/analytics/."""

from django.urls import path

from .views import AnalyticsReportView, CollectView, LiveTicketView

collect = [path("collect/", CollectView.as_view(), name="analytics-collect")]
report = [
    path("", AnalyticsReportView.as_view(), name="admin-analytics"),
    path("live-ticket/", LiveTicketView.as_view(), name="admin-analytics-live-ticket"),
]
