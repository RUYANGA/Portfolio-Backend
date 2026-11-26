"""Routes: `collect` under /api/analytics/, `report` under /api/admin/analytics/."""

from django.urls import path

from .views import AnalyticsReportView, CollectView

collect = [path("collect/", CollectView.as_view(), name="analytics-collect")]
report = [path("", AnalyticsReportView.as_view(), name="admin-analytics")]
