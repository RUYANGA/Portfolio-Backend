"""Public booking API: slots, booking with calendar invitations, cancelling."""

from datetime import datetime, timedelta
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.booking import availability, invites
from apps.booking.models import WEEKDAYS, Booking, BookingSettings

OWNER_CALENDARS = "me@gmail.com\nme@company.com"


def part(message, prefix: str) -> str:
    """The body of the email's first alternative part whose type starts with `prefix`."""
    return next(str(content) for content, kind in getattr(message, "alternatives", []) if kind.startswith(prefix))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    BOOKING_BUSY_CALENDARS=[],
    SITE_URL="https://portfolio.example.com",
)
class BookingApiTests(TestCase):
    def setUp(self):
        cache.clear()
        config = BookingSettings.load()
        config.weekly_hours = {day: [["00:00", "23:59"]] for day in WEEKDAYS}
        config.min_notice_hours = 1
        config.daily_limit = 0
        config.calendar_emails = OWNER_CALENDARS
        config.meeting_link = "https://meet.google.com/abc-defg-hij"
        config.save()
        self.now = timezone.now()

    def slots(self, type_="intro-call"):
        start = self.now.isoformat()
        end = (self.now + timedelta(days=2)).isoformat()
        res = self.client.get("/api/booking/slots/", {"type": type_, "start": start, "end": end})
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()["slots"]

    def book(self, **fields):
        body = {
            "type": "intro-call",
            "start": fields.get("start") or self.slots()[0],
            "name": "Sarah Mitchell",
            "email": "sarah@northwind.io",
            "company": "Northwind",
            "notes": "Backend role <b>on</b> the platform team.",
            "timezone": "Europe/London",
        }
        body.update(fields)
        return self.client.post("/api/booking/", body, content_type="application/json")

    def test_info_lists_active_meeting_types(self):
        data = self.client.get("/api/booking/").json()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["timezone"], "Africa/Kigali")
        slugs = [t["slug"] for t in data["meeting_types"]]
        self.assertEqual(slugs[:2], ["intro-call", "technical-discussion"])
        self.assertEqual(len(slugs), 9)
        self.assertIn("job-interview", slugs)
        self.assertEqual(
            next(t for t in data["meeting_types"] if t["slug"] == "quick-question")["duration_minutes"], 15
        )

    def test_slots_are_utc_and_respect_notice(self):
        slots = self.slots()
        self.assertTrue(slots and all(s.endswith("Z") for s in slots))
        earliest = min(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in slots)
        self.assertGreaterEqual(earliest, self.now + timedelta(hours=1))

    def test_slot_requests_are_validated(self):
        self.assertEqual(self.client.get("/api/booking/slots/", {"type": "nope"}).status_code, 404)
        res = self.client.get("/api/booking/slots/", {"type": "intro-call", "start": "tomorrow", "end": "later"})
        self.assertEqual(res.status_code, 400)

    def test_booking_sends_invitations_to_visitor_and_both_calendars(self):
        res = self.book()
        self.assertEqual(res.status_code, 201, res.content)
        booking = Booking.objects.get()
        self.assertEqual(booking.end - booking.start, timedelta(minutes=30))
        self.assertEqual(booking.visitor_timezone, "Europe/London")
        self.assertEqual(res.json()["meeting_link"], "https://meet.google.com/abc-defg-hij")
        self.assertEqual(booking.meeting_link, "https://meet.google.com/abc-defg-hij")

        visitor, owner = mail.outbox
        self.assertEqual(visitor.to, ['"Sarah Mitchell" <sarah@northwind.io>'])
        self.assertTrue(visitor.subject.startswith("Confirmed: Intro call with "))
        self.assertEqual(owner.to, ["me@gmail.com", "me@company.com"])
        self.assertEqual(owner.reply_to, ['"Sarah Mitchell" <sarah@northwind.io>'])
        self.assertTrue(owner.subject.startswith("New booking: Intro call with Sarah Mitchell"))

        for message in (visitor, owner):
            ics = part(message, "text/calendar")
            self.assertIn("METHOD:REQUEST", ics)
            self.assertIn(f"UID:{booking.uid}@portfolio-booking", ics)
            for address in ("me@gmail.com", "me@company.com", "sarah@northwind.io"):
                self.assertIn(f"mailto:{address}", ics.replace("\r\n ", ""))
            self.assertIn("BEGIN:VALARM", ics)
            self.assertEqual(message.attachments[0][0], "invite.ics")
        visitor_ics = part(visitor, "text/calendar").replace("\r\n ", "")
        self.assertIn("RSVP=TRUE", visitor_ics)
        self.assertIn("PARTSTAT=NEEDS-ACTION", visitor_ics)

        visitor_html = part(visitor, "text/html")
        self.assertIn("Join video call", visitor_html)
        self.assertIn(f"https://portfolio.example.com/book/manage/{booking.cancel_token}", visitor_html)
        self.assertIn("calendar.google.com/calendar/render", visitor_html)
        self.assertIn("&lt;b&gt;on&lt;/b&gt;", visitor_html)
        self.assertIn("calendar invitation is attached", visitor_html.lower())
        owner_html = part(owner, "text/html")
        self.assertIn("Northwind", owner_html)
        self.assertIn("https://portfolio.example.com/admin/bookings", owner_html)

    def test_a_booked_slot_is_no_longer_offered_or_bookable(self):
        start = self.slots()[0]
        self.assertEqual(self.book(start=start).status_code, 201)
        self.assertNotIn(start, self.slots())
        res = self.book(start=start, email="other@example.com")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(Booking.objects.count(), 1)

    def test_times_outside_availability_are_rejected(self):
        self.assertEqual(self.book(start=(self.now + timedelta(minutes=10)).isoformat()).status_code, 409)
        self.assertEqual(self.book(start=(self.now + timedelta(days=90)).isoformat()).status_code, 409)

    def test_honeypot_and_disabled_booking(self):
        self.assertEqual(self.book(website="http://spam").status_code, 400)
        start = self.slots()[0]
        BookingSettings.objects.update(is_enabled=False)
        self.assertEqual(self.book(start=start).status_code, 403)
        self.assertEqual(self.client.get("/api/booking/slots/", {"type": "intro-call"}).status_code, 404)
        self.assertFalse(self.client.get("/api/booking/").json()["enabled"])

    @override_settings(BOOKING_BUSY_CALENDARS=["https://calendar.google.com/private.ics"])
    def test_unreadable_calendar_returns_503(self):
        with mock.patch.object(availability, "_fetch", side_effect=OSError("down")):
            with self.assertLogs("apps.booking.availability", "WARNING"):
                res = self.client.get(
                    "/api/booking/slots/",
                    {
                        "type": "intro-call",
                        "start": self.now.isoformat(),
                        "end": (self.now + timedelta(days=1)).isoformat(),
                    },
                )
        self.assertEqual(res.status_code, 503)

    def test_visitor_can_view_and_cancel_from_the_email_link(self):
        self.book()
        booking = Booking.objects.get()
        mail.outbox.clear()

        data = self.client.get(f"/api/booking/manage/{booking.cancel_token}/").json()
        self.assertTrue(data["can_cancel"])
        res = self.client.post(
            f"/api/booking/manage/{booking.cancel_token}/cancel/", {"reason": "Clash"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(booking.sequence, 1)

        self.assertEqual(len(mail.outbox), 2)
        for message in mail.outbox:
            ics = part(message, "text/calendar")
            self.assertIn("METHOD:CANCEL", ics)
            self.assertIn("SEQUENCE:1", ics)
            self.assertIn(f"UID:{booking.uid}@portfolio-booking", ics)
        self.assertTrue(mail.outbox[1].subject.startswith("Cancelled: Intro call with Sarah Mitchell"))

        again = self.client.post(f"/api/booking/manage/{booking.cancel_token}/cancel/")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.client.get("/api/booking/manage/not-a-token/").status_code, 404)

    def test_mail_failure_keeps_the_booking(self):
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            with self.assertLogs("apps.booking.api", "ERROR"):
                self.assertEqual(self.book().status_code, 201)
        self.assertEqual(Booking.objects.count(), 1)
