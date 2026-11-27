"""Meeting reminders: emails before each meeting, and pop-up reminders in the invitation."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from apps.booking.invites import build_ics, lead_text
from apps.booking.management.commands.send_booking_reminders import send_due_reminders
from apps.booking.models import Booking, BookingSettings

NOW = datetime(2026, 12, 1, 8, 0, tzinfo=dt_timezone.utc)
OWNER = "owner@gmail.example\nowner@work.example"
THREE_DAYS = timedelta(days=3)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="x@example.com")
class ReminderTests(TestCase):
    def setUp(self):
        config = BookingSettings.load()
        config.calendar_emails = OWNER
        config.meeting_link = "https://meet.example.com/abc"
        config.save()

    def book(self, starts_in: timedelta, booked_ago: timedelta = THREE_DAYS, **fields) -> Booking:
        start = NOW + starts_in
        booking = Booking.objects.create(
            title="Intro call",
            start=start,
            end=start + timedelta(minutes=30),
            name="Ada Lovelace",
            email="ada@example.com",
            visitor_timezone="Europe/London",
            **fields,
        )
        Booking.objects.filter(pk=booking.pk).update(created_at=NOW - booked_ago)
        booking.refresh_from_db()
        return booking

    def test_default_reminders_are_a_day_and_an_hour_before(self):
        self.assertEqual(BookingSettings.load().reminder_minutes, [1440, 60])
        self.assertEqual(lead_text(1440), "1 day")
        self.assertEqual(lead_text(90), "1 hour 30 minutes")

    def test_day_before_reminder_goes_to_you_and_the_guest_once(self):
        booking = self.book(timedelta(hours=23, minutes=50))
        self.assertEqual(send_due_reminders(NOW), 1)
        self.assertEqual(len(mail.outbox), 2)
        to_owner, to_guest = mail.outbox
        self.assertEqual(to_owner.to, ["owner@gmail.example", "owner@work.example"])
        self.assertIn("Reminder: Intro call with Ada Lovelace in 23 hours 50 minutes", to_owner.subject)
        self.assertIn("ada@example.com", to_guest.to[0])
        self.assertIn("starts in", to_guest.body)
        html = getattr(to_guest, "alternatives", [])[0][0]
        self.assertIn("https://meet.example.com/abc", str(html))  # Join button
        self.assertEqual(to_guest.attachments, [])  # no invitation: the event is already in the calendar
        booking.refresh_from_db()
        self.assertEqual(booking.reminders_sent, [1440])

        self.assertEqual(send_due_reminders(NOW + timedelta(minutes=5)), 0)  # not again
        self.assertEqual(len(mail.outbox), 2)

    def test_hour_before_reminder_follows(self):
        booking = self.book(timedelta(minutes=55))
        booking.reminders_sent = [1440]
        booking.save()
        self.assertEqual(send_due_reminders(NOW), 1)
        self.assertIn("in 55 minutes", mail.outbox[0].subject)
        booking.refresh_from_db()
        self.assertEqual(booking.reminders_sent, [60, 1440])

    def test_several_overdue_reminders_send_one_email(self):
        self.book(timedelta(minutes=50))  # both the 1-day and 1-hour times have passed
        send_due_reminders(NOW)
        self.assertEqual(len(mail.outbox), 2)  # one each for you and the guest, not four

    def test_no_reminder_right_after_booking(self):
        booking = self.book(timedelta(minutes=50), booked_ago=timedelta(minutes=5))
        self.assertEqual(send_due_reminders(NOW), 0)
        self.assertEqual(mail.outbox, [])
        booking.refresh_from_db()
        self.assertEqual(booking.reminders_sent, [60, 1440])  # handled: they just got the confirmation

    def test_cancelled_far_and_past_meetings_are_skipped(self):
        self.book(timedelta(minutes=30), status=Booking.Status.CANCELLED)
        self.book(timedelta(days=3))
        self.book(-timedelta(minutes=10))
        self.assertEqual(send_due_reminders(NOW), 0)
        self.assertEqual(mail.outbox, [])

    def test_guest_reminder_can_be_turned_off_and_reminders_disabled(self):
        config = BookingSettings.load()
        config.remind_guest = False
        config.save()
        self.book(timedelta(minutes=30))
        send_due_reminders(NOW)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("owner@gmail.example", mail.outbox[0].to)

        config.reminder_minutes = []
        config.save()
        self.book(timedelta(minutes=20))
        self.assertEqual(send_due_reminders(NOW), 0)

    def test_invitation_has_a_pop_up_for_each_reminder(self):
        booking = self.book(timedelta(days=2))
        config = BookingSettings.load()
        config.reminder_minutes = [1440, 60, 15]
        ics = build_ics(booking, config, "Owner", ["owner@gmail.example"]).decode()
        self.assertEqual(ics.count("BEGIN:VALARM"), 3)
        for trigger in ("TRIGGER:-P1D", "TRIGGER:-PT1H", "TRIGGER:-PT15M"):
            self.assertIn(trigger, ics)
        self.assertNotIn("VALARM", build_ics(booking, config, "Owner", [], cancel=True).decode())


class ReminderSettingsApiTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner", "o@example.com", "owner-pass-123")
        res = self.client.post(
            "/api/admin/auth/login/",
            {"username": "owner", "password": "owner-pass-123"},
            content_type="application/json",
        )
        self.token = f"Token {res.json()['token']}"

    def patch(self, data):
        return self.client.patch(
            "/api/admin/booking/settings/", data, content_type="application/json", HTTP_AUTHORIZATION=self.token
        )

    def test_reminder_times_are_validated(self):
        ok = self.patch({"reminder_minutes": [2880, 60, 10], "remind_guest": False})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["reminder_minutes"], [2880, 60, 10])
        for bad in ([1], [60, 60], [99999], ["60"], [1, 2, 3, 4, 5, 6]):
            self.assertEqual(self.patch({"reminder_minutes": bad}).status_code, 400, bad)
