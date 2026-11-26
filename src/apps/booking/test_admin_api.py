"""Dashboard booking endpoints: settings, calendar check, meeting types, bookings and cancelling."""

import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.booking import availability
from apps.booking.models import Booking, BookingSettings, MeetingType

GOOGLE = "https://calendar.google.com/calendar/ical/x/private-y/basic.ics"
OUTLOOK = "https://outlook.office365.com/owa/calendar/a/b/reachcalendar.ics"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    BOOKING_BUSY_CALENDARS=[GOOGLE, OUTLOOK],
)
class BookingAdminApiTests(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_superuser("owner", "o@example.com", "owner-pass-123")
        res = self.client.post(
            "/api/admin/auth/login/",
            {"username": "owner", "password": "owner-pass-123"},
            content_type="application/json",
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Token {res.json()['token']}"}

    def api(self, method, url, data=None):
        body = json.dumps(data) if data is not None else None
        return getattr(self.client, method)(
            f"/api/admin/booking/{url}", body, content_type="application/json", **self.auth
        )

    def booking(self, hours_from_now, **fields):
        start = timezone.now() + timedelta(hours=hours_from_now)
        values = {"title": "Intro call", "start": start, "end": start + timedelta(minutes=30)}
        values.update({"name": "Sarah", "email": "sarah@example.com", **fields})
        return Booking.objects.create(**values)

    def test_requires_a_staff_token(self):
        self.assertEqual(self.client.get("/api/admin/booking/settings/").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/booking/bookings/").status_code, 401)

    def test_settings_read_and_update(self):
        data = self.api("get", "settings/").json()
        self.assertEqual(data["timezone"], "Africa/Kigali")
        self.assertEqual(data["calendar_emails"], [])
        self.assertEqual(data["calendars"]["configured"], 2)

        res = self.api(
            "patch",
            "settings/",
            {
                "calendar_emails": ["me@gmail.com", "me@company.com"],
                "weekly_hours": {"mon": [["10:00", "16:00"]], "tue": []},
                "buffer_minutes": 10,
            },
        )
        self.assertEqual(res.status_code, 200, res.content)
        config = BookingSettings.load()
        self.assertEqual(config.calendar_email_list, ["me@gmail.com", "me@company.com"])
        self.assertEqual(config.buffer_minutes, 10)

    def test_invalid_settings_are_rejected(self):
        self.assertEqual(
            self.api("patch", "settings/", {"weekly_hours": {"mon": [["17:00", "09:00"]]}}).status_code, 400
        )
        self.assertEqual(self.api("patch", "settings/", {"timezone": "Nowhere/City"}).status_code, 400)
        self.assertEqual(self.api("patch", "settings/", {"calendar_emails": ["not-an-email"]}).status_code, 400)

    def test_calendar_check_reports_each_calendar(self):
        def fetch(url):
            if url == OUTLOOK:
                raise OSError("403 Forbidden")
            return b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

        with (
            mock.patch.object(availability, "_fetch", side_effect=fetch),
            self.assertLogs("apps.booking.availability", "WARNING"),
        ):
            feeds = self.api("post", "calendars/check/").json()["feeds"]
        self.assertEqual([(f["label"], f["ok"]) for f in feeds], [("Google Calendar", True), ("Outlook", False)])
        self.assertIn("403", feeds[1]["error"])

    def test_meeting_types_crud(self):
        res = self.api("post", "meeting-types/", {"title": "Mentoring", "slug": "mentoring", "duration_minutes": 60})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(
            self.api("post", "meeting-types/", {"title": "x", "slug": "x", "duration_minutes": 5}).status_code, 400
        )
        pk = res.json()["id"]
        self.api("patch", f"meeting-types/{pk}/", {"is_active": False})
        self.assertFalse(MeetingType.objects.get(pk=pk).is_active)

    def test_bookings_are_listed_by_period(self):
        upcoming = self.booking(24)
        past = self.booking(-24)
        cancelled = self.booking(48, status="cancelled")
        ids = lambda when: [b["id"] for b in self.api("get", f"bookings/?when={when}").json()]  # noqa: E731
        self.assertEqual(ids("upcoming"), [upcoming.pk])
        self.assertEqual(ids("past"), [past.pk])
        self.assertEqual(ids("cancelled"), [cancelled.pk])

        overview = self.client.get("/api/admin/overview/", HTTP_AUTHORIZATION=self.auth["HTTP_AUTHORIZATION"]).json()
        self.assertEqual(overview["counts"]["upcoming_bookings"], 1)

    def test_owner_can_cancel_and_everyone_is_told(self):
        BookingSettings.objects.update(calendar_emails="me@gmail.com\nme@company.com")
        booking = self.booking(24)
        res = self.api("post", f"bookings/{booking.pk}/cancel/", {"reason": "Travelling that day"})
        self.assertEqual(res.status_code, 200, res.content)
        booking.refresh_from_db()
        self.assertEqual(
            (booking.status, booking.cancel_reason, booking.sequence), ("cancelled", "Travelling that day", 1)
        )
        visitor, owner = mail.outbox
        ics = getattr(visitor, "alternatives", [])[1][0]
        self.assertIn("METHOD:CANCEL", str(ics))
        self.assertEqual(owner.to, ["me@gmail.com", "me@company.com"])
        self.assertEqual(self.api("post", f"bookings/{booking.pk}/cancel/").status_code, 409)
