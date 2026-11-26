"""
Dashboard endpoints for booking, under /api/admin/booking/ (staff token required).

settings/              GET, PATCH  availability rules, invitation addresses, video link
calendars/check/       POST        read the busy calendars now and report each one's status
meeting-types/         CRUD + reorder
bookings/              list (?when=upcoming|past|cancelled), retrieve
bookings/<id>/cancel/  POST {reason} cancel and send calendar cancellations
"""

from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.portfolio.api.admin.auth import AdminAPIView, ExpiringTokenAuthentication
from apps.portfolio.api.admin.views import AdminViewSet

from .api import cancel_booking
from .availability import CalendarUnavailable, _key, calendar_busy, feed_statuses
from .invites import owner_name
from .models import Booking, BookingSettings, MeetingType, split_emails, validate_weekly_hours


class BookingSettingsSerializer(serializers.ModelSerializer):
    calendar_emails = serializers.ListField(child=serializers.EmailField(), required=False)

    class Meta:
        model = BookingSettings
        exclude = ["id"]
        read_only_fields = ["updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["calendar_emails"] = split_emails(instance.calendar_emails)
        return data

    def to_internal_value(self, data):
        values = super().to_internal_value(data)
        if "calendar_emails" in values:
            values["calendar_emails"] = "\n".join(values["calendar_emails"])
        return values

    def validate_weekly_hours(self, value):
        try:
            validate_weekly_hours(value)
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Unknown time zone. Use a name like Africa/Kigali.")
        return value

    def validate_slot_step_minutes(self, value):
        if value < 5:
            raise serializers.ValidationError("Use at least 5 minutes.")
        return value


def calendars_payload() -> dict:
    return {"configured": len(settings.BOOKING_BUSY_CALENDARS), "feeds": feed_statuses()}


class BookingSettingsView(AdminAPIView):
    def get(self, request):
        data = BookingSettingsSerializer(BookingSettings.load()).data
        return Response({**data, "calendars": calendars_payload()})

    def patch(self, request):
        serializer = BookingSettingsSerializer(BookingSettings.load(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({**serializer.data, "calendars": calendars_payload()})


class CalendarCheckView(AdminAPIView):
    """Read every busy calendar now (bypassing the 5-minute cache) and report the result."""

    def post(self, request):
        for url in settings.BOOKING_BUSY_CALENDARS:
            cache.delete(_key(url, "fresh"))
        config = BookingSettings.load()
        try:
            calendar_busy(timezone.now() + timedelta(days=config.max_days_ahead + 2), config.tz)
        except CalendarUnavailable:
            pass  # the per-calendar status below says which one failed
        return Response(calendars_payload())


class MeetingTypeAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetingType
        fields = ["id", "title", "slug", "duration_minutes", "description", "is_active", "order"]

    def validate_duration_minutes(self, value):
        if not 10 <= value <= 240:
            raise serializers.ValidationError("Choose between 10 and 240 minutes.")
        return value


class MeetingTypeAdminViewSet(AdminViewSet):
    queryset = MeetingType.objects.all()
    serializer_class = MeetingTypeAdminSerializer


class BookingAdminSerializer(serializers.ModelSerializer):
    meeting_type: serializers.SlugRelatedField = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "title",
            "meeting_type",
            "start",
            "end",
            "name",
            "email",
            "company",
            "notes",
            "visitor_timezone",
            "status",
            "cancelled_at",
            "cancel_reason",
            "created_at",
        ]
        read_only_fields = fields


class BookingAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    authentication_classes = [ExpiringTokenAuthentication]
    permission_classes = AdminAPIView.permission_classes
    serializer_class = BookingAdminSerializer
    pagination_class = None

    def get_queryset(self):
        bookings = Booking.objects.select_related("meeting_type")
        when = self.request.query_params.get("when", "")
        now = timezone.now()
        if when == "upcoming":
            return bookings.filter(status=Booking.Status.CONFIRMED, end__gte=now).order_by("start")
        if when == "past":
            return bookings.filter(status=Booking.Status.CONFIRMED, end__lt=now).order_by("-start")
        if when == "cancelled":
            return bookings.filter(status=Booking.Status.CANCELLED).order_by("-cancelled_at")
        return bookings.order_by("-start")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        if not booking.is_active:
            return Response({"detail": "This booking is already cancelled."}, status=status.HTTP_409_CONFLICT)
        cancel_booking(booking, reason=str(request.data.get("reason", ""))[:300], cancelled_by=owner_name())
        return Response(self.get_serializer(booking).data)
