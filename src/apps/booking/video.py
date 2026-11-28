"""Video meeting links for bookings.

Providers are best-effort: if credentials are missing or a provider call fails, the booking still
succeeds and falls back to the configured manual meeting link.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib import error, parse, request
from uuid import uuid4

from django.conf import settings

from .models import Booking, BookingSettings

logger = logging.getLogger(__name__)


@dataclass
class VideoMeeting:
    url: str
    provider: str


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int = 12) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST")
    with request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - configured provider URLs only
        raw = res.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _post_form(url: str, payload: dict[str, str], timeout: int = 12) -> dict:
    body = parse.urlencode(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - configured provider URLs only
        raw = res.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _google_access_token() -> str | None:
    client_id = getattr(settings, "GOOGLE_CALENDAR_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_CALENDAR_CLIENT_SECRET", "")
    refresh_token = getattr(settings, "GOOGLE_CALENDAR_REFRESH_TOKEN", "")
    if not (client_id and client_secret and refresh_token):
        return None
    data = _post_form(
        "https://oauth2.googleapis.com/token",
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    token = data.get("access_token")
    return str(token) if token else None


def _google_meet(booking: Booking, config: BookingSettings, owner: str) -> str | None:
    token = _google_access_token()
    calendar_id = getattr(settings, "GOOGLE_CALENDAR_ID", "") or "primary"
    if not token:
        return None
    payload = {
        "summary": f"{booking.title}: {booking.name} and {owner}",
        "description": booking.notes or f"Meeting booked through {owner}'s portfolio.",
        "start": {"dateTime": booking.start.isoformat()},
        "end": {"dateTime": booking.end.isoformat()},
        "attendees": [{"email": booking.email, "displayName": booking.name}]
        + ([{"email": e} for e in config.calendar_email_list]),
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    url = (
        "https://www.googleapis.com/calendar/v3/calendars/"
        f"{parse.quote(calendar_id, safe='')}/events?conferenceDataVersion=1&sendUpdates=none"
    )
    data = _post_json(url, payload, {"Authorization": f"Bearer {token}"})
    link = data.get("hangoutLink")
    if link:
        return str(link)
    entry_points = ((data.get("conferenceData") or {}).get("entryPoints") or [])
    for entry in entry_points:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return str(entry["uri"])
    return None


def _teams_access_token() -> str | None:
    tenant_id = getattr(settings, "MICROSOFT_TENANT_ID", "")
    client_id = getattr(settings, "MICROSOFT_CLIENT_ID", "")
    client_secret = getattr(settings, "MICROSOFT_CLIENT_SECRET", "")
    if not (tenant_id and client_id and client_secret):
        return None
    data = _post_form(
        f"https://login.microsoftonline.com/{parse.quote(tenant_id, safe='')}/oauth2/v2.0/token",
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
    )
    token = data.get("access_token")
    return str(token) if token else None


def _teams_meeting(booking: Booking, owner: str) -> str | None:
    token = _teams_access_token()
    user_id = getattr(settings, "MICROSOFT_USER_ID", "")
    if not (token and user_id):
        return None
    payload = {
        "subject": f"{booking.title}: {booking.name} and {owner}",
        "startDateTime": booking.start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endDateTime": booking.end.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    data = _post_json(
        f"https://graph.microsoft.com/v1.0/users/{parse.quote(user_id, safe='')}/onlineMeetings",
        payload,
        {"Authorization": f"Bearer {token}"},
    )
    link = data.get("joinWebUrl") or data.get("joinUrl")
    return str(link) if link else None


def create_meeting_link(booking: Booking, config: BookingSettings, owner: str) -> VideoMeeting | None:
    provider = getattr(config, "video_provider", "manual") or "manual"
    try:
        if provider == "google_meet":
            url = _google_meet(booking, config, owner)
            return VideoMeeting(url=url, provider=provider) if url else None
        if provider == "microsoft_teams":
            url = _teams_meeting(booking, owner)
            return VideoMeeting(url=url, provider=provider) if url else None
    except (error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Video provider %s failed: %s", provider, exc)
    except Exception:  # noqa: BLE001
        logger.exception("Video provider %s failed", provider)

    if config.meeting_link:
        return VideoMeeting(url=config.meeting_link, provider="manual")
    return None
