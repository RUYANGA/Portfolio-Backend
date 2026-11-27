"""
Sends meeting reminders ("starts in 1 hour") by email to you and the guest.

Google Calendar and Outlook don't use the reminders inside emailed invitations, so these emails are
what reliably notifies you on your phone. The reminder times are set in Dashboard → Booking settings.

    python manage.py send_booking_reminders            # once (e.g. from cron)
    python manage.py send_booking_reminders --loop 60  # keep checking every 60 seconds

scripts/start.sh runs it with --loop next to the web server.
"""

import logging
import time
from datetime import datetime, timedelta

from django.core.mail import get_connection
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.booking.invites import reminder_emails
from apps.booking.models import Booking, BookingSettings

log = logging.getLogger("apps.booking.reminders")


def send_due_reminders(now: datetime | None = None) -> int:
    """Send every reminder that is due now; returns how many bookings were reminded."""
    now = now or timezone.now()
    leads = sorted(set(BookingSettings.load().reminder_minutes or []))
    if not leads:
        return 0
    reminded = 0
    with transaction.atomic():
        # skip_locked: if two checkers ever run at once, each booking is handled by only one of them.
        upcoming = Booking.objects.select_for_update(skip_locked=True).filter(
            status=Booking.Status.CONFIRMED, start__gt=now, start__lte=now + timedelta(minutes=max(leads))
        )
        for booking in upcoming:
            handled = set(booking.reminders_sent or [])
            due = [m for m in leads if m not in handled and booking.start - timedelta(minutes=m) <= now]
            if not due:
                continue
            closest = min(due)  # one email, even when several reminder times have passed
            # Booked after this reminder time (e.g. an hour before): they just had the confirmation.
            if booking.created_at <= booking.start - timedelta(minutes=closest):
                try:
                    get_connection().send_messages(reminder_emails(booking, now))
                except Exception:  # noqa: BLE001 - keep going; it's retried on the next check
                    log.exception("Couldn't send the reminder for booking %s", booking.pk)
                    continue
                reminded += 1
            booking.reminders_sent = sorted(handled | set(due))
            booking.save(update_fields=["reminders_sent"])
    return reminded


class Command(BaseCommand):
    help = "Email meeting reminders that are due (to you and the guest)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", type=int, default=0, help="Keep running, checking every N seconds.")

    def handle(self, *args, loop: int = 0, **options):
        while True:
            count = send_due_reminders()
            if count or not loop:
                self.stdout.write(f"Sent reminders for {count} meeting(s).")
            if not loop:
                return
            time.sleep(max(15, loop))
