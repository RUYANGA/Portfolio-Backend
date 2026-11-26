"""Emails the site sends: the owner's notification for each contact-form message."""

from email.utils import parseaddr
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.portfolio.models import ContactMessage, Profile


def initials(name: str) -> str:
    letters = [word[0] for word in name.split() if word[:1].isalpha()]
    return "".join(letters[:2]).upper() or "?"


def named(display_name: str, address: str) -> str:
    """'"Name" <address>'. Django encodes non-ASCII names when it sends the email."""
    clean = display_name.replace("\\", "").replace('"', "").replace("\n", " ").replace("\r", " ").strip()
    return f'"{clean}" <{address}>' if clean else address


def sender_address(display_name: str) -> str:
    """DEFAULT_FROM_EMAIL with a readable name, unless it already carries one."""
    name, address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    return settings.DEFAULT_FROM_EMAIL if name else named(display_name, address)


def contact_notification(message: ContactMessage, recipient: str) -> EmailMultiAlternatives:
    """
    The owner's copy of a contact-form message: HTML with a plain-text fallback.
    Reply-To is the visitor, so answering the email goes straight to them.
    """
    owner = Profile.objects.values_list("name", flat=True).first() or "Portfolio"
    subject_line = message.subject or "New message"
    received = timezone.localtime(message.created_at)
    reply_subject = f"Re: {subject_line}"
    context = {
        "message": message,
        "owner": owner,
        "owner_initials": initials(owner),
        "subject_line": subject_line,
        "initials": initials(message.name),
        "received_date": received.strftime("%A, %d %B %Y").replace(" 0", " "),
        "received_time": received.strftime("%H:%M"),
        "timezone_name": settings.TIME_ZONE.split("/")[-1].replace("_", " "),
        "reply_url": f"mailto:{quote(message.email, safe='@')}?subject={quote(reply_subject)}",
        "inbox_url": f"{settings.SITE_URL}/admin/messages" if settings.SITE_URL else "",
        "site_url": settings.SITE_URL,
        "site_host": settings.SITE_URL.split("://")[-1],
        "preview": " ".join(message.message.split())[:110],
    }
    email = EmailMultiAlternatives(
        subject=f"New message from {message.name} · {subject_line}",
        body=render_to_string("portfolio/emails/contact_notification.txt", context),
        from_email=sender_address(f"{owner} · Portfolio"),
        to=[recipient],
        reply_to=[named(message.name, message.email)],
    )
    email.attach_alternative(render_to_string("portfolio/emails/contact_notification.html", context), "text/html")
    return email
