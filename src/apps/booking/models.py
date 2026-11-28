"""Meeting booking: your availability rules, the meeting types visitors choose from, and bookings."""

import secrets
import uuid
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def default_weekly_hours():
    """Weekdays 09:00 to 17:00 with a lunch break; weekends off."""
    workday = [["09:00", "12:30"], ["13:30", "17:00"]]
    return {day: (workday if day not in ("sat", "sun") else []) for day in WEEKDAYS}


# How long before a meeting reminders go out (minutes): a day before and an hour before.
DEFAULT_REMINDERS = [1440, 60]
MAX_REMINDER_MINUTES = 7 * 24 * 60


def default_reminders():
    return list(DEFAULT_REMINDERS)


def validate_reminders(value) -> None:
    if not isinstance(value, list) or len(value) > 5:
        raise ValidationError("Choose up to five reminder times.")
    for minutes in value:
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 5 <= minutes <= MAX_REMINDER_MINUTES:
            raise ValidationError("Each reminder must be between 5 minutes and 7 days before the meeting.")
    if len(set(value)) != len(value):
        raise ValidationError("Each reminder time can only be chosen once.")


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def split_emails(value: str) -> list[str]:
    return [item.strip() for item in (value or "").replace(",", "\n").splitlines() if item.strip()]


class BookingSettings(models.Model):
    """Single record: when you can be booked and where invitations go."""

    is_enabled = models.BooleanField(default=True, help_text="Turn off to hide the booking page.")
    timezone = models.CharField(max_length=64, default="Africa/Kigali", help_text="Your time zone (IANA name).")
    weekly_hours = models.JSONField(
        default=default_weekly_hours,
        help_text='Bookable hours per weekday, e.g. {"mon": [["09:00", "17:00"]], "sat": []}.',
    )
    min_notice_hours = models.PositiveSmallIntegerField(default=12, help_text="How soon a meeting can start.")
    max_days_ahead = models.PositiveSmallIntegerField(default=30, help_text="How far ahead visitors can book.")
    buffer_minutes = models.PositiveSmallIntegerField(default=15, help_text="Free time kept around every meeting.")
    slot_step_minutes = models.PositiveSmallIntegerField(
        default=30, help_text="Start times are offered every N minutes."
    )
    daily_limit = models.PositiveSmallIntegerField(default=4, help_text="Most bookings in one day (0 = no limit).")
    calendar_emails = models.TextField(
        blank=True,
        help_text="Every address that should receive the calendar invitation, one per line "
        "(e.g. your Gmail and your Outlook work address).",
    )
    meeting_link = models.URLField(blank=True, help_text="Default video call link added to every invitation.")
    video_provider = models.CharField(
        max_length=20,
        choices=[("manual", "Manual link"), ("google_meet", "Google Meet"), ("microsoft_teams", "Microsoft Teams")],
        default="manual",
        help_text="How video calls are created for bookings.",
    )
    reminder_minutes = models.JSONField(
        default=default_reminders,
        blank=True,
        validators=[validate_reminders],
        help_text="Minutes before each meeting when reminders go out, e.g. [1440, 60]. Empty = none.",
    )
    remind_guest = models.BooleanField(default=True, help_text="Send the guest a reminder too.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "booking settings"
        verbose_name_plural = "booking settings"

    @classmethod
    def load(cls) -> "BookingSettings":
        obj = cls.objects.first()
        return obj if obj is not None else cls.objects.create()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def calendar_email_list(self) -> list[str]:
        return split_emails(self.calendar_emails)

    def clean(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError({"timezone": "Unknown time zone. Use a name like Africa/Kigali."})
        validate_weekly_hours(self.weekly_hours)
        if self.slot_step_minutes < 5:
            raise ValidationError({"slot_step_minutes": "Use at least 5 minutes."})

    def __str__(self):
        return "Booking settings"


def validate_weekly_hours(value) -> None:
    if not isinstance(value, dict) or set(value) - set(WEEKDAYS):
        raise ValidationError({"weekly_hours": f"Use the weekdays {', '.join(WEEKDAYS)} as keys."})
    for day, ranges in value.items():
        if not isinstance(ranges, list):
            raise ValidationError({"weekly_hours": f"{day}: expected a list of [start, end] pairs."})
        previous_end = None
        for pair in ranges:
            try:
                start, end = (parse_hhmm(v) for v in pair)
            except (TypeError, ValueError):
                raise ValidationError({"weekly_hours": f"{day}: times must look like 09:00."})
            if start >= end:
                raise ValidationError({"weekly_hours": f"{day}: each range must end after it starts."})
            if previous_end and start < previous_end:
                raise ValidationError({"weekly_hours": f"{day}: ranges must be in order and not overlap."})
            previous_end = end


class MeetingType(models.Model):
    """A kind of meeting visitors can book, e.g. a 30-minute intro call."""

    title = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    description = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True, help_text="Only active types are offered.")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def clean(self):
        if not 10 <= self.duration_minutes <= 240:
            raise ValidationError({"duration_minutes": "Choose between 10 and 240 minutes."})

    def __str__(self):
        return f"{self.title} ({self.duration_minutes} min)"


def new_token() -> str:
    return secrets.token_urlsafe(24)


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    meeting_type = models.ForeignKey(MeetingType, null=True, blank=True, on_delete=models.SET_NULL)
    # Kept on the booking so it reads the same if the meeting type is later edited or deleted.
    title = models.CharField(max_length=80)
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField()
    name = models.CharField(max_length=120)
    email = models.EmailField()
    company = models.CharField(max_length=120, blank=True)
    notes = models.TextField(max_length=2000, blank=True, help_text="What the visitor wants to discuss.")
    visitor_timezone = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    # Calendar invitation identity: the same UID with a higher SEQUENCE updates or cancels the event.
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sequence = models.PositiveIntegerField(default=0)
    cancel_token = models.CharField(max_length=64, default=new_token, unique=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)
    meeting_link = models.URLField(blank=True, help_text="Video call link for this booking.")
    meeting_provider = models.CharField(max_length=20, blank=True, help_text="Provider that created the video call.")
    reminders_sent = models.JSONField(
        default=list, blank=True, help_text="Reminder times (minutes before) already handled for this booking."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start"]
        constraints = [
            models.CheckConstraint(condition=models.Q(end__gt=models.F("start")), name="booking_ends_after_start")
        ]

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.CONFIRMED

    def __str__(self):
        return f"{self.title} with {self.name} at {self.start:%Y-%m-%d %H:%M} UTC"
