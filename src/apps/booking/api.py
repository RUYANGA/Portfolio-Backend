"""
Public booking API used by the /book page.

GET  /api/booking/                        meeting types and booking rules
GET  /api/booking/slots/?type=&start=&end= free start times (UTC) between two instants
POST /api/booking/                        book a slot (re-checked under a lock, then invitations sent)
GET  /api/booking/manage/<token>/          the visitor's booking (from the link in their email)
POST /api/booking/manage/<token>/cancel/   cancel it (sends calendar cancellations)
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .availability import CalendarUnavailable, available_slots, is_available
from .invites import booking_emails, owner_name
from .models import Booking, BookingSettings, MeetingType
from .video import (
    create_meeting_link,
    google_connect_url,
    google_exchange_code,
    insert_google_event_for_guest,
)
from django.conf import settings
from django.http import HttpResponseRedirect
import secrets

logger = logging.getLogger(__name__)

UNAVAILABLE = "Availability can't be checked right now. Please try again in a few minutes."


def send_booking_emails(booking: Booking, cancel: bool = False, cancelled_by: str = "") -> None:
    """Send the invitations; the booking is already saved, so a mail failure is only logged."""
    for message in booking_emails(booking, cancel=cancel, cancelled_by=cancelled_by):
        try:
            message.send()
        except Exception:  # noqa: BLE001
            logger.exception("Booking email to %s failed", ", ".join(message.to))


def booking_payload(booking: Booking, config: BookingSettings) -> dict:
    return {
        "title": booking.title,
        "start": booking.start,
        "end": booking.end,
        "name": booking.name,
        "email": booking.email,
        "status": booking.status,
        "visitor_timezone": booking.visitor_timezone,
        "meeting_link": (booking.meeting_link or config.meeting_link) if booking.is_active else "",
        "can_cancel": booking.is_active and booking.start > timezone.now(),
        "manage_token": booking.cancel_token,
        "google_calendar_connected": bool(getattr(settings, "GOOGLE_CALENDAR_CLIENT_ID", "") and getattr(settings, "GOOGLE_CALENDAR_CLIENT_SECRET", "")),
    }


class MeetingTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetingType
        fields = ["slug", "title", "duration_minutes", "description"]


class BookingRequestSerializer(serializers.Serializer):
    type = serializers.SlugField()
    start = serializers.DateTimeField()
    name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    company = serializers.CharField(max_length=120, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=2000)
    timezone = serializers.CharField(max_length=64, required=False, allow_blank=True)
    # Honeypot: hidden from people, filled in by bots.
    website = serializers.CharField(required=False, allow_blank=True)

    def validate_type(self, value):
        meeting_type = MeetingType.objects.filter(slug=value, is_active=True).first()
        if meeting_type is None:
            raise serializers.ValidationError("Choose one of the meeting types.")
        return meeting_type

    def validate_name(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Enter your name.")
        return value.strip()

    def validate_notes(self, value):
        text = value.strip()
        if not text:
            raise serializers.ValidationError("Please tell me what you'd like to discuss.")
        return text

    def validate_timezone(self, value):
        try:
            return ZoneInfo(value).key if value else ""
        except (ZoneInfoNotFoundError, ValueError):
            return ""

    def validate(self, attrs):
        if attrs.pop("website", ""):
            raise serializers.ValidationError("Booking could not be made.")
        return attrs


class BookingView(APIView):
    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "booking"
            return [ScopedRateThrottle()]
        return []

    def get(self, request):
        config = BookingSettings.load()
        types = MeetingType.objects.filter(is_active=True)
        return Response(
            {
                "enabled": config.is_enabled and types.exists(),
                "timezone": config.timezone,
                "max_days_ahead": config.max_days_ahead,
                "min_notice_hours": config.min_notice_hours,
                "meeting_types": MeetingTypeSerializer(types, many=True).data,
            }
        )

    def post(self, request):
        config = BookingSettings.load()
        if not config.is_enabled:
            return Response({"detail": "Booking is closed at the moment."}, status=status.HTTP_403_FORBIDDEN)
        serializer = BookingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        meeting_type: MeetingType = data["type"]
        start: datetime = data["start"].astimezone(ZoneInfo("UTC")).replace(second=0, microsecond=0)

        try:
            is_available(meeting_type, start, config=config)  # reads the calendars before taking the lock
            with transaction.atomic():
                # One booking at a time: the settings row is the lock, so two visitors can't take a slot together.
                config = BookingSettings.objects.select_for_update().get(pk=config.pk)
                if not is_available(meeting_type, start, config=config):
                    return Response(
                        {"start": ["That time was just taken. Please choose another."]},
                        status=status.HTTP_409_CONFLICT,
                    )
                booking = Booking.objects.create(
                    meeting_type=meeting_type,
                    title=meeting_type.title,
                    start=start,
                    end=start + timedelta(minutes=meeting_type.duration_minutes),
                    name=data["name"],
                    email=data["email"],
                    company=data.get("company", "").strip(),
                    notes=data.get("notes", "").strip(),
                    visitor_timezone=data.get("timezone", ""),
                )
            meeting = create_meeting_link(booking, config, owner_name())
            if meeting and meeting.url:
                booking.meeting_link = meeting.url
                booking.meeting_provider = meeting.provider
                booking.save(update_fields=["meeting_link", "meeting_provider"])
        except CalendarUnavailable:
            return Response({"detail": UNAVAILABLE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        send_booking_emails(booking)
        return Response(booking_payload(booking, config), status=status.HTTP_201_CREATED)


class SlotsView(APIView):
    def get(self, request):
        config = BookingSettings.load()
        meeting_type = MeetingType.objects.filter(slug=request.query_params.get("type", ""), is_active=True).first()
        if not config.is_enabled or meeting_type is None:
            return Response({"detail": "Unknown meeting type."}, status=status.HTTP_404_NOT_FOUND)
        start = parse_datetime(request.query_params.get("start", ""))
        end = parse_datetime(request.query_params.get("end", ""))
        if not start or not end or timezone.is_naive(start) or timezone.is_naive(end) or end <= start:
            return Response(
                {"detail": "Send start and end as ISO 8601 times with an offset, e.g. 2026-12-01T00:00:00Z."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            slots = available_slots(meeting_type, start, end, config=config)
        except CalendarUnavailable:
            return Response({"detail": UNAVAILABLE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {
                "type": meeting_type.slug,
                "duration_minutes": meeting_type.duration_minutes,
                "slots": [slot.isoformat().replace("+00:00", "Z") for slot in slots],
            }
        )


class ManageBookingView(APIView):
    def get(self, request, token):
        booking = get_object_or_404(Booking, cancel_token=token)
        return Response(booking_payload(booking, BookingSettings.load()))


class CancelBookingView(APIView):
    def post(self, request, token):
        booking = get_object_or_404(Booking, cancel_token=token)
        if not booking.is_active:
            return Response({"detail": "This booking is already cancelled."}, status=status.HTTP_409_CONFLICT)
        if booking.start <= timezone.now():
            return Response({"detail": "This meeting has already started."}, status=status.HTTP_409_CONFLICT)
        cancel_booking(booking, reason=str(request.data.get("reason", ""))[:300], cancelled_by=booking.name)
        return Response(booking_payload(booking, BookingSettings.load()))


def cancel_booking(booking: Booking, reason: str = "", cancelled_by: str = "") -> None:
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancel_reason = reason.strip()
    booking.sequence += 1
    booking.save(update_fields=["status", "cancelled_at", "cancel_reason", "sequence"])
    send_booking_emails(booking, cancel=True, cancelled_by=cancelled_by)


class GoogleCalendarConnectView(APIView):
    def post(self, request, token):
        booking = get_object_or_404(Booking, cancel_token=token)
        if not booking.is_active:
            return Response({"detail": "This booking is no longer active."}, status=status.HTTP_409_CONFLICT)
        state = secrets.token_urlsafe(24)
        request.session[f"gcal_booking_{state}"] = {"token": token}
        request.session.modified = True
        try:
            url = google_connect_url(request, state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Google connect URL failed")
            return Response({"detail": "Google Calendar is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not url:
            return Response({"detail": "Google Calendar is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"url": url})


class GoogleCalendarCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        error = request.query_params.get("error")
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        data = request.session.pop(f"gcal_booking_{state}", None)
        site = getattr(settings, "SITE_URL", "") or next(iter(settings.CORS_ALLOWED_ORIGINS), "http://localhost:3000")
        base = site.rstrip("/")
        if error or not code or not data:
            return HttpResponseRedirect(f"{base}/book/manage/{data.get('token','')}/?gcal=error" if data else f"{base}/book?gcal=error")
        booking = get_object_or_404(Booking, cancel_token=data["token"])
        try:
            access = google_exchange_code(request, code)
            if not access:
                raise ValueError("No access token")
            insert_google_event_for_guest(booking, BookingSettings.load(), owner_name(), access)
            return HttpResponseRedirect(f"{base}/book/manage/{booking.cancel_token}/?gcal=added")
        except Exception:  # noqa: BLE001
            logger.exception("Google guest calendar insert failed")
            return HttpResponseRedirect(f"{base}/book/manage/{booking.cancel_token}/?gcal=error")
