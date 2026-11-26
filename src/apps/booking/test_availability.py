"""Availability: weekly hours minus busy time from Google/Outlook feeds and existing bookings."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from apps.booking import availability
from apps.booking.models import Booking, BookingSettings, MeetingType

UTC = dt_timezone.utc
GOOGLE = "https://calendar.google.com/calendar/ical/me%40gmail.com/private-abc/basic.ics"
OUTLOOK = "https://outlook.office365.com/owa/calendar/abc/def/reachcalendar.ics"

# Monday 30 Nov 2026, 08:00 in Kigali (UTC+2). With 12 h notice, Tuesday is the first bookable day.
NOW = datetime(2026, 11, 30, 6, 0, tzinfo=UTC)
TUESDAY = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)


def utc(day, hour, minute=0):
    return datetime(2026, 12, day, hour, minute, tzinfo=UTC)


def ics(*events: str) -> bytes:
    body = "\r\n".join(events)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n{body}\r\nEND:VCALENDAR\r\n".encode()


def event(uid, start, end, extra=""):
    lines = ["BEGIN:VEVENT", f"UID:{uid}", "DTSTAMP:20261101T000000Z", f"DTSTART:{start}", f"DTEND:{end}"]
    lines += [line for line in extra.split("|") if line]
    return "\r\n".join(lines + ["END:VEVENT"])


EMPTY = ics()
# Google: Tuesday 10:00-11:00 Kigali (08:00-09:00 UTC), plus a "free" event that must be ignored.
GOOGLE_FEED = ics(
    event("g1", "20261201T080000Z", "20261201T090000Z"),
    event("g2", "20261201T120000Z", "20261201T130000Z", "TRANSP:TRANSPARENT"),
)
# Outlook: a daily 14:30 UTC stand-up (recurring), a FREE block and a cancelled meeting.
OUTLOOK_FEED = ics(
    event("o1", "20261130T143000Z", "20261130T150000Z", "RRULE:FREQ=DAILY;COUNT=10"),
    event("o2", "20261201T113000Z", "20261201T120000Z", "X-MICROSOFT-CDO-BUSYSTATUS:FREE"),
    event("o3", "20261201T120000Z", "20261201T123000Z", "STATUS:CANCELLED"),
)


def feeds(mapping):
    def fetch(url):
        result = mapping[url]
        if isinstance(result, Exception):
            raise result
        return result

    return mock.patch.object(availability, "_fetch", side_effect=fetch)


class AvailabilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.config = BookingSettings.load()
        self.call = MeetingType.objects.get(slug="intro-call")  # 30 minutes, created by the migration

    def slots(self, day=TUESDAY, **kwargs):
        return availability.available_slots(
            self.call, day, day + timedelta(days=1), now=NOW, config=self.config, **kwargs
        )

    @override_settings(BOOKING_BUSY_CALENDARS=[])
    def test_weekly_hours_become_slots_in_utc(self):
        slots = self.slots()
        # 09:00-12:30 and 13:30-17:00 Kigali = 07:00-10:30 and 11:30-15:00 UTC, every 30 minutes.
        self.assertEqual(slots[0], utc(1, 7))
        self.assertEqual(slots[-1], utc(1, 14, 30))
        self.assertEqual(len(slots), 14)
        self.assertNotIn(utc(1, 10, 30), slots)  # would run into the lunch break

    @override_settings(BOOKING_BUSY_CALENDARS=[])
    def test_weekends_and_short_notice_are_excluded(self):
        saturday = datetime(2026, 12, 5, tzinfo=UTC)
        self.assertEqual(self.slots(saturday), [])
        monday = datetime(2026, 11, 30, tzinfo=UTC)
        self.assertEqual(self.slots(monday), [])  # all of Monday is within 12 h notice

    @override_settings(BOOKING_BUSY_CALENDARS=[GOOGLE, OUTLOOK])
    def test_busy_time_from_both_calendars_blocks_slots(self):
        with feeds({GOOGLE: GOOGLE_FEED, OUTLOOK: OUTLOOK_FEED}):
            slots = self.slots()
        # Google 08:00-09:00 UTC with a 15-minute buffer blocks 07:30, 08:00, 08:30 and 09:00.
        for blocked in (utc(1, 7, 30), utc(1, 8), utc(1, 8, 30), utc(1, 9)):
            self.assertNotIn(blocked, slots)
        self.assertIn(utc(1, 7), slots)
        self.assertIn(utc(1, 9, 30), slots)
        # Outlook's recurring 14:30 stand-up blocks 14:00 and 14:30.
        self.assertNotIn(utc(1, 14), slots)
        self.assertNotIn(utc(1, 14, 30), slots)
        # Free, transparent and cancelled events don't block anything.
        self.assertIn(utc(1, 11, 30), slots)
        self.assertIn(utc(1, 12), slots)

    @override_settings(BOOKING_BUSY_CALENDARS=[])
    def test_existing_bookings_and_daily_limit(self):
        Booking.objects.create(
            title="Intro call", start=utc(1, 11, 30), end=utc(1, 12), name="A", email="a@example.com"
        )
        slots = self.slots()
        self.assertNotIn(utc(1, 11, 30), slots)
        self.assertNotIn(utc(1, 12), slots)  # inside the 15-minute buffer
        self.assertIn(utc(1, 12, 30), slots)

        self.config.daily_limit = 1
        self.assertEqual(self.slots(), [])

    @override_settings(BOOKING_BUSY_CALENDARS=[])
    def test_cancelled_bookings_free_the_slot(self):
        Booking.objects.create(
            title="Intro call", start=utc(1, 7), end=utc(1, 7, 30), name="A", email="a@example.com", status="cancelled"
        )
        self.assertIn(utc(1, 7), self.slots())

    @override_settings(BOOKING_BUSY_CALENDARS=[GOOGLE])
    def test_unreadable_calendar_offers_no_slots(self):
        with feeds({GOOGLE: OSError("timeout")}):
            with self.assertLogs("apps.booking.availability", "WARNING"):
                with self.assertRaises(availability.CalendarUnavailable):
                    self.slots()
        status = availability.feed_statuses()[0]
        self.assertEqual(status["label"], "Google Calendar")
        self.assertFalse(status["ok"])

    @override_settings(BOOKING_BUSY_CALENDARS=[GOOGLE])
    def test_recent_copy_is_used_while_a_calendar_is_down(self):
        with feeds({GOOGLE: GOOGLE_FEED}):
            first = self.slots()
        cache.delete(availability._key(GOOGLE, "fresh"))
        with feeds({GOOGLE: OSError("timeout")}), self.assertLogs("apps.booking.availability", "WARNING"):
            self.assertEqual(self.slots(), first)

    @override_settings(BOOKING_BUSY_CALENDARS=[GOOGLE])
    def test_feed_is_cached_between_requests(self):
        with feeds({GOOGLE: GOOGLE_FEED}) as fetch:
            self.slots()
            self.slots()
        self.assertEqual(fetch.call_count, 1)

    def test_all_day_busy_events_block_the_whole_day(self):
        holiday = "\r\n".join(
            [
                "BEGIN:VEVENT",
                "UID:h",
                "DTSTAMP:20261101T000000Z",
                "DTSTART;VALUE=DATE:20261201",
                "DTEND;VALUE=DATE:20261202",
                "END:VEVENT",
            ]
        )
        busy = availability.parse_busy(ics(holiday), NOW, NOW + timedelta(days=5), self.config.tz)
        # Midnight to midnight in Kigali (UTC+2).
        self.assertEqual(busy, [(utc(1, 0) - timedelta(hours=2), utc(2, 0) - timedelta(hours=2))])

    def test_weekly_hours_are_validated(self):
        bad_values: list[dict[str, list[list[str]]]] = [
            {"mon": [["17:00", "09:00"]]},
            {"funday": []},
            {"mon": [["9am", "5pm"]]},
            {"mon": [["09:00", "12:00"], ["11:00", "13:00"]]},
        ]
        for bad in bad_values:
            self.config.weekly_hours = bad
            with self.assertRaises(ValidationError):
                self.config.clean()
        self.config.weekly_hours = {"mon": [["09:00", "12:00"]]}
        self.config.timezone = "Mars/Olympus"
        with self.assertRaises(ValidationError):
            self.config.clean()


class FeedRefreshAndErrorTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(BOOKING_BUSY_CALENDARS=[GOOGLE], BOOKING_CALENDAR_REFRESH_SECONDS=60)
    def test_calendar_is_read_again_after_the_refresh_interval(self):
        config = BookingSettings.load()
        horizon = NOW + timedelta(days=40)
        with feeds({GOOGLE: GOOGLE_FEED}) as fetch, mock.patch.object(availability.timezone, "now", return_value=NOW):
            availability.calendar_busy(horizon, config.tz)
            availability.calendar_busy(horizon, config.tz)  # within the minute: cached
            self.assertEqual(fetch.call_count, 1)
        with (
            feeds({GOOGLE: GOOGLE_FEED}) as fetch,
            mock.patch.object(availability.timezone, "now", return_value=NOW + timedelta(seconds=61)),
        ):
            availability.calendar_busy(horizon, config.tz)  # a minute later: read again
            self.assertEqual(fetch.call_count, 1)

    def test_refresh_interval_has_a_floor(self):
        with override_settings(BOOKING_CALENDAR_REFRESH_SECONDS=1):
            self.assertEqual(availability.fresh_seconds(), 15)
        with override_settings(BOOKING_CALENDAR_REFRESH_SECONDS=300):
            self.assertEqual(availability.fresh_seconds(), 300)

    def test_errors_are_explained(self):
        import urllib.error

        gone = urllib.error.HTTPError(GOOGLE, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        self.assertIn("probably reset", availability.explain(gone))
        busy_server = urllib.error.HTTPError(GOOGLE, 503, "x", {}, None)  # type: ignore[arg-type]
        self.assertIn("temporary", availability.explain(busy_server))
        self.assertIn("couldn't be reached", availability.explain(urllib.error.URLError("Name or service not known")))
        self.assertIn("isn't a valid URL", availability.explain(ValueError("unknown url type: '\"https'")))

    @override_settings(BOOKING_BUSY_CALENDARS=[GOOGLE])
    def test_dashboard_status_carries_the_explanation(self):
        import urllib.error

        error = urllib.error.HTTPError(GOOGLE, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        with feeds({GOOGLE: error}), self.assertLogs("apps.booking.availability", "WARNING"):
            with self.assertRaises(availability.CalendarUnavailable):
                availability.calendar_busy(NOW + timedelta(days=5), BookingSettings.load().tz)
        status = availability.feed_statuses()[0]
        self.assertFalse(status["ok"])
        self.assertIn("HTTP 404", status["error"])
