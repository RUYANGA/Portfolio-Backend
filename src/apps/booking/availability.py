"""
Free meeting slots: your weekly hours, minus busy time in your calendars and existing bookings.

Busy time is read from each calendar's private iCal address (BOOKING_BUSY_CALENDARS), e.g. the
Google Calendar "secret address in iCal format" and an Outlook "published calendar" ICS link.
Recurring events are expanded; events marked free/transparent or cancelled are ignored.
Each feed is read again every minute (BOOKING_CALENDAR_REFRESH_SECONDS).
If a feed can't be read and no recent copy exists,
no slots are offered: refusing a booking is better than double-booking you.
"""

import hashlib
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from urllib.parse import urlparse

import recurring_ical_events
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from icalendar import Calendar

from .models import WEEKDAYS, Booking, BookingSettings, MeetingType, parse_hhmm

logger = logging.getLogger(__name__)

UTC = dt_timezone.utc
Interval = tuple[datetime, datetime]

STALE_SECONDS = 6 * 3600  # if a calendar is down, trust the last copy this long
MAX_FEED_BYTES = 15 * 1024 * 1024
MAX_RANGE_DAYS = 62


class CalendarUnavailable(Exception):
    """A busy-time calendar could not be read and there is no recent copy."""


@dataclass
class FeedState:
    intervals: list[Interval]
    horizon_end: datetime
    fetched_at: datetime


def feed_label(url: str) -> str:
    host = urlparse(url).hostname or ""
    if "google" in host:
        return "Google Calendar"
    if "outlook" in host or "office365" in host or "live.com" in host:
        return "Outlook"
    if "icloud" in host:
        return "iCloud"
    return host or "Calendar"


def _key(url: str, kind: str) -> str:
    return f"booking:feed:{kind}:{hashlib.sha256(url.encode()).hexdigest()[:24]}"


def fresh_seconds() -> int:
    """How long a calendar read is reused (BOOKING_CALENDAR_REFRESH_SECONDS, default 60)."""
    return max(15, int(getattr(settings, "BOOKING_CALENDAR_REFRESH_SECONDS", 60)))


def explain(exc: Exception) -> str:
    """A reason the owner can act on, for the dashboard."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403, 404, 410):
            return (
                f"The calendar refused the link (HTTP {exc.code}). It was probably reset or unpublished: "
                "copy the current private iCal link into BOOKING_BUSY_CALENDARS and redeploy."
            )
        return f"The calendar server answered HTTP {exc.code}. It is usually temporary."
    if isinstance(exc, urllib.error.URLError):
        return f"The calendar server couldn't be reached ({exc.reason}). Check the link, or try again shortly."
    if isinstance(exc, ValueError) and "unknown url type" in str(exc).lower():
        return "The link isn't a valid URL. Check BOOKING_BUSY_CALENDARS for extra characters."
    if isinstance(exc, TimeoutError):
        return "The calendar took too long to answer. It is usually temporary."
    return f"The calendar couldn't be read ({type(exc).__name__}: {exc})"[:300]


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url.replace("webcal://", "https://", 1), headers={"User-Agent": "portfolio-booking/1.0"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - URL comes from settings
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("Calendar feed is too large")
    return data


def _as_utc(value, owner_tz) -> datetime:
    """DTSTART/DTEND value (date or datetime, aware or floating) as an aware UTC datetime."""
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = value.replace(tzinfo=owner_tz)
        return value.astimezone(UTC)
    # All-day event: from midnight to midnight in your time zone.
    return datetime(value.year, value.month, value.day, tzinfo=owner_tz).astimezone(UTC)


def _is_busy(event) -> bool:
    if str(event.get("STATUS", "")).upper() == "CANCELLED":
        return False
    if str(event.get("TRANSP", "")).upper() == "TRANSPARENT":
        return False
    # Outlook publishes free/busy as this property (FREE, TENTATIVE, BUSY, OOF, WORKINGELSEWHERE).
    if str(event.get("X-MICROSOFT-CDO-BUSYSTATUS", "")).upper() in {"FREE", "WORKINGELSEWHERE"}:
        return False
    return True


def parse_busy(ics: bytes, start: datetime, end: datetime, owner_tz) -> list[Interval]:
    calendar = Calendar.from_ical(ics)
    intervals = []
    for event in recurring_ical_events.of(calendar).between(start, end):
        if event.name != "VEVENT" or not _is_busy(event) or "DTSTART" not in event:
            continue
        begin = _as_utc(event["DTSTART"].dt, owner_tz)
        if "DTEND" in event:
            finish = _as_utc(event["DTEND"].dt, owner_tz)
        elif "DURATION" in event:
            finish = begin + event["DURATION"].dt
        else:
            finish = begin + (timedelta(days=1) if not isinstance(event["DTSTART"].dt, datetime) else timedelta())
        if finish > begin:
            intervals.append((begin, finish))
    return merge(intervals)


def merge(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for begin, finish in sorted(intervals):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((begin, finish))
    return merged


def _record_status(url: str, ok: bool, error: str = "", events: int = 0) -> None:
    cache.set(
        _key(url, "status"),
        {"ok": ok, "error": error, "busy_blocks": events, "checked_at": timezone.now().isoformat()},
        STALE_SECONDS,
    )


def feed_busy(url: str, horizon_end: datetime, owner_tz) -> list[Interval]:
    now = timezone.now()
    for kind, max_age in (("fresh", fresh_seconds()), ("stale", STALE_SECONDS)):
        state: FeedState | None = cache.get(_key(url, kind))
        if state and state.horizon_end >= horizon_end and (now - state.fetched_at).total_seconds() <= max_age:
            if kind == "fresh":
                return state.intervals
            break  # a stale copy exists; still try to refresh first
    try:
        start = now - timedelta(days=1)
        intervals = parse_busy(_fetch(url), start, horizon_end, owner_tz)
    except Exception as exc:  # noqa: BLE001 - network, HTTP and parse errors all mean "unreadable"
        logger.warning("Busy calendar %s unreadable: %s", feed_label(url), exc)
        _record_status(url, False, explain(exc))
        stale: FeedState | None = cache.get(_key(url, "stale"))
        if stale and stale.horizon_end >= horizon_end and (now - stale.fetched_at).total_seconds() <= STALE_SECONDS:
            return stale.intervals
        raise CalendarUnavailable(feed_label(url)) from exc
    state = FeedState(intervals=intervals, horizon_end=horizon_end, fetched_at=now)
    cache.set(_key(url, "fresh"), state, fresh_seconds())
    cache.set(_key(url, "stale"), state, STALE_SECONDS)
    _record_status(url, True, events=len(intervals))
    return intervals


def calendar_busy(horizon_end: datetime, owner_tz) -> list[Interval]:
    busy: list[Interval] = []
    for url in settings.BOOKING_BUSY_CALENDARS:
        busy.extend(feed_busy(url, horizon_end, owner_tz))
    return merge(busy)


def feed_statuses() -> list[dict]:
    """For the dashboard: whether each configured calendar was read successfully."""
    statuses = []
    for url in settings.BOOKING_BUSY_CALENDARS:
        status = cache.get(_key(url, "status")) or {"ok": None, "error": "", "busy_blocks": 0, "checked_at": None}
        statuses.append({"label": feed_label(url), **status})
    return statuses


def _overlaps(begin: datetime, finish: datetime, intervals: list[Interval]) -> bool:
    return any(begin < b_end and finish > b_start for b_start, b_end in intervals)


def available_slots(
    meeting_type: MeetingType,
    range_start: datetime,
    range_end: datetime,
    now: datetime | None = None,
    config: BookingSettings | None = None,
) -> list[datetime]:
    """Start times (aware, UTC) at which `meeting_type` fits, between range_start and range_end."""
    config = config or BookingSettings.load()
    now = now or timezone.now()
    owner_tz = config.tz
    duration = timedelta(minutes=meeting_type.duration_minutes)
    buffer = timedelta(minutes=config.buffer_minutes)
    step = timedelta(minutes=max(config.slot_step_minutes, 5))

    earliest = max(range_start, now + timedelta(hours=config.min_notice_hours))
    latest = min(range_end, now + timedelta(days=config.max_days_ahead))
    latest = min(latest, earliest + timedelta(days=MAX_RANGE_DAYS))
    if earliest >= latest:
        return []

    horizon_end = (now + timedelta(days=config.max_days_ahead + 2)).replace(minute=0, second=0, microsecond=0)
    busy = calendar_busy(horizon_end, owner_tz)
    bookings = list(
        Booking.objects.filter(
            status=Booking.Status.CONFIRMED,
            start__lt=latest + duration + buffer + timedelta(days=1),
            end__gt=earliest - buffer - timedelta(days=1),
        ).values_list("start", "end")
    )
    blocked = merge([(b - buffer, e + buffer) for b, e in busy + bookings])
    per_day: dict[date, int] = {}
    for b_start, _ in bookings:
        day = b_start.astimezone(owner_tz).date()
        per_day[day] = per_day.get(day, 0) + 1

    slots: list[datetime] = []
    day = earliest.astimezone(owner_tz).date()
    last_day = latest.astimezone(owner_tz).date()
    while day <= last_day:
        if config.daily_limit and per_day.get(day, 0) >= config.daily_limit:
            day += timedelta(days=1)
            continue
        for start_text, end_text in config.weekly_hours.get(WEEKDAYS[day.weekday()], []):
            window_start = datetime.combine(day, parse_hhmm(start_text), owner_tz)
            window_end = datetime.combine(day, parse_hhmm(end_text), owner_tz)
            candidate = window_start
            while candidate + duration <= window_end:
                begin = candidate.astimezone(UTC)
                finish = begin + duration
                if earliest <= begin <= latest and not _overlaps(begin, finish, blocked):
                    slots.append(begin)
                candidate += step
        day += timedelta(days=1)
    return slots


def is_available(meeting_type: MeetingType, start: datetime, config: BookingSettings | None = None) -> bool:
    """Whether a booking for `meeting_type` may start exactly at `start` (re-checked on submit)."""
    start = start.astimezone(UTC)
    return start in available_slots(
        meeting_type, start - timedelta(minutes=1), start + timedelta(minutes=1), config=config
    )
