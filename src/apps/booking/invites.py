"""
Calendar invitations and emails for bookings.

Every booking is one calendar event (same UID) with you and the visitor as attendees. It is sent
as an iCalendar invitation (METHOD:REQUEST), which Gmail/Google Calendar and Outlook add to the
calendar automatically, with a reminder. Cancelling sends METHOD:CANCEL with a higher SEQUENCE,
which removes the event from every calendar it was added to.
"""

from datetime import datetime, timedelta
from email.utils import parseaddr
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from icalendar import Alarm, Calendar, Event, vCalAddress, vText

from apps.portfolio.models import Profile

from .models import Booking, BookingSettings


def site_url() -> str:
    """The public site's address (SITE_URL, else the first CORS origin)."""
    explicit = getattr(settings, "SITE_URL", "")
    return (explicit or next(iter(settings.CORS_ALLOWED_ORIGINS), "")).rstrip("/")


def owner_name() -> str:
    return Profile.objects.values_list("name", flat=True).first() or "Portfolio"


def owner_addresses(config: BookingSettings) -> list[str]:
    """Where your copy of the invitation goes: the booking addresses, else the contact address."""
    if config.calendar_email_list:
        return config.calendar_email_list
    fallback = settings.CONTACT_NOTIFY_EMAIL or Profile.objects.values_list("email", flat=True).first()
    return [fallback] if fallback else []


def named(display_name: str, address: str) -> str:
    """'"Name" <address>'. Django encodes non-ASCII names when it sends the email."""
    clean = display_name.replace("\\", "").replace('"', "").replace("\n", " ").replace("\r", " ").strip()
    return f'"{clean}" <{address}>' if clean else address


def organizer_address() -> str:
    return parseaddr(settings.DEFAULT_FROM_EMAIL)[1] or "noreply@localhost"


def manage_url(booking: Booking) -> str:
    base = site_url()
    return f"{base}/book/manage/{booking.cancel_token}" if base else ""


def location(config: BookingSettings) -> str:
    return config.meeting_link or "Video call (the link will be sent before the meeting)"


def build_ics(
    booking: Booking, config: BookingSettings, owner: str, attendees: list[str], cancel: bool = False
) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Portfolio booking//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "CANCEL" if cancel else "REQUEST")

    event = Event()
    event.add("uid", f"{booking.uid}@portfolio-booking")
    event.add("sequence", booking.sequence)
    event.add("dtstamp", timezone.now())
    event.add("created", booking.created_at or timezone.now())
    event.add("dtstart", booking.start)
    event.add("dtend", booking.end)
    event.add("summary", f"{booking.title}: {booking.name} and {owner}")
    event.add("location", location(config))
    if config.meeting_link:
        event.add("url", config.meeting_link)
    details = [f"{booking.title} booked through {owner}'s portfolio."]
    if booking.company:
        details.append(f"Company: {booking.company}")
    if booking.notes:
        details.append(f"Agenda:\n{booking.notes}")
    if config.meeting_link:
        details.append(f"Join: {config.meeting_link}")
    if manage_url(booking):
        details.append(f"Need to cancel? {manage_url(booking)}")
    event.add("description", "\n\n".join(details))
    event.add("status", "CANCELLED" if cancel else "CONFIRMED")
    event.add("transp", "OPAQUE")

    organizer = vCalAddress(f"mailto:{organizer_address()}")
    organizer.params["cn"] = vText(owner)
    event["organizer"] = organizer
    for name, address in [(owner, a) for a in attendees] + [(booking.name, booking.email)]:
        attendee = vCalAddress(f"mailto:{address}")
        attendee.params["cn"] = vText(name)
        attendee.params["role"] = vText("REQ-PARTICIPANT")
        attendee.params["partstat"] = vText("ACCEPTED")
        attendee.params["rsvp"] = vText("FALSE")
        event.add("attendee", attendee, encode=0)

    if not cancel:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"{booking.title} with {booking.name}")
        alarm.add("trigger", timedelta(minutes=-15))
        event.add_component(alarm)

    calendar.add_component(event)
    return calendar.to_ical()


def _zone(name: str, fallback: ZoneInfo) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else fallback
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


def _when(start: datetime, end: datetime, zone: ZoneInfo) -> dict[str, str]:
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    offset = local_start.strftime("%z")
    return {
        "date": local_start.strftime("%A, %d %B %Y").replace(" 0", " "),
        "time": f"{local_start:%H:%M} – {local_end:%H:%M}",
        "zone": f"{zone.key.replace('_', ' ')} (UTC{offset[:3]}:{offset[3:]})",
        "day": str(local_start.day),
        "month": local_start.strftime("%b").upper(),
    }


def calendar_links(booking: Booking, config: BookingSettings, owner: str) -> dict[str, str]:
    stamp = "%Y%m%dT%H%M%SZ"
    start, end = booking.start.astimezone(ZoneInfo("UTC")), booking.end.astimezone(ZoneInfo("UTC"))
    title = f"{booking.title} with {owner}"
    google = "https://calendar.google.com/calendar/render?" + urlencode(
        {
            "action": "TEMPLATE",
            "text": title,
            "dates": f"{start:{stamp}}/{end:{stamp}}",
            "details": booking.notes,
            "location": location(config),
        },
        quote_via=quote,
    )
    outlook = "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(
        {
            "subject": title,
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
            "body": booking.notes,
            "location": location(config),
            "path": "/calendar/action/compose",
            "rru": "addevent",
        },
        quote_via=quote,
    )
    return {"google": google, "outlook": outlook}


def _message(subject, to, reply_to, template_context, ics: bytes, cancel: bool) -> EmailMultiAlternatives:
    owner = template_context["owner"]
    email = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("booking/emails/booking.txt", template_context),
        from_email=(
            settings.DEFAULT_FROM_EMAIL
            if parseaddr(settings.DEFAULT_FROM_EMAIL)[0]
            else named(f"{owner} · Portfolio", organizer_address())
        ),
        to=to,
        reply_to=reply_to,
    )
    email.attach_alternative(render_to_string("booking/emails/booking.html", template_context), "text/html")
    method = "CANCEL" if cancel else "REQUEST"
    # As an alternative part, Gmail and Outlook show RSVP-style controls and add the event;
    # as an attachment, any other calendar app can import it.
    email.attach_alternative(ics.decode(), f"text/calendar; method={method}; charset=UTF-8")
    email.attach("invite.ics", ics, f"application/ics; method={method}")
    return email


def booking_emails(booking: Booking, cancel: bool = False, cancelled_by: str = "") -> list[EmailMultiAlternatives]:
    """The visitor's confirmation and your notification (or both cancellations), with the invitation."""
    config = BookingSettings.load()
    owner = owner_name()
    owners = owner_addresses(config)
    ics = build_ics(booking, config, owner, owners, cancel=cancel)
    base = {
        "booking": booking,
        "owner": owner,
        "cancel": cancel,
        "cancelled_by": cancelled_by,
        "location": location(config),
        "meeting_link": config.meeting_link,
        "manage_url": manage_url(booking),
        "inbox_url": f"{site_url()}/admin/bookings" if site_url() else "",
        "site_url": site_url(),
        "site_host": site_url().split("://")[-1],
        "links": calendar_links(booking, config, owner),
    }
    visitor_when = _when(booking.start, booking.end, _zone(booking.visitor_timezone, config.tz))
    owner_when = _when(booking.start, booking.end, config.tz)
    prefix = "Cancelled" if cancel else "Confirmed"
    messages = [
        _message(
            f"{prefix}: {booking.title} with {owner}, {visitor_when['date']}",
            [named(booking.name, booking.email)],
            [named(owner, owners[0])] if owners else None,
            {**base, "for_owner": False, "when": visitor_when},
            ics,
            cancel,
        )
    ]
    if owners:
        subject = (
            f"Cancelled: {booking.title} with {booking.name}, {owner_when['date']}"
            if cancel
            else f"New booking: {booking.title} with {booking.name}, {owner_when['date']} at {owner_when['time'][:5]}"
        )
        messages.append(
            _message(
                subject,
                owners,
                [named(booking.name, booking.email)],
                {**base, "for_owner": True, "when": owner_when},
                ics,
                cancel,
            )
        )
    return messages
