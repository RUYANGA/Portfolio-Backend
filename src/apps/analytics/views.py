"""
Visitor analytics.

POST /api/analytics/collect/   called by the Next.js site's server (never by browsers directly), with
                               the shared ANALYTICS_KEY. It forwards the visitor's IP, browser and the
                               country/city that Vercel works out from the IP.
GET  /api/admin/analytics/     the dashboard report (?days=1..365&tz=Area/City&country=…), staff token
                               required. Built in report.py.
"""

import hashlib
import hmac
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Value
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.portfolio.api.admin.auth import AdminAPIView

from . import report
from .models import Hit

MAX_DURATION = 30 * 60  # a tab left open overnight shouldn't count as hours of reading
EVENTS = {"cv_download", "booking", "contact", "project_open", "lab_open", "share", "outbound", "section"}

BOT = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|headless|lighthouse|pingdom|uptime|monitor|"
    r"curl|wget|python-requests|httpx|axios|go-http|java/|okhttp|scrapy|vercel-screenshot",
    re.I,
)
# Paths that carry a private token are counted without it.
PRIVATE_PATHS = [(re.compile(r"^/book/manage/[^/]+"), "/book/manage")]


# ---------- collecting ----------


def parse_user_agent(ua: str) -> tuple[str, str, str]:
    """(device, browser, os) from a User-Agent string, good enough for a dashboard."""
    if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        device = "Tablet"
    elif re.search(r"Mobi|iPhone|iPod|Android", ua):
        device = "Mobile"
    else:
        device = "Desktop"

    browsers = [
        (r"Edg(e|A|iOS)?/", "Edge"),
        (r"OPR/|Opera", "Opera"),
        (r"SamsungBrowser", "Samsung Internet"),
        (r"Firefox|FxiOS", "Firefox"),
        (r"Chrome|CriOS", "Chrome"),
        (r"Version/[\d.]+.*Safari", "Safari"),
    ]
    browser = next((name for pattern, name in browsers if re.search(pattern, ua)), "Other")

    systems = [
        (r"iPhone|iPad|iPod", "iOS"),
        (r"Android", "Android"),
        (r"Windows", "Windows"),
        (r"CrOS", "ChromeOS"),
        (r"Mac OS X|Macintosh", "macOS"),
        (r"Linux", "Linux"),
    ]
    os_name = next((name for pattern, name in systems if re.search(pattern, ua)), "Other")
    return device, browser, os_name


def clean_path(value: Any) -> str:
    path = str(value or "/").split("?")[0].split("#")[0][:200] or "/"
    if not path.startswith("/"):
        path = "/" + path
    for pattern, replacement in PRIVATE_PATHS:
        path = pattern.sub(replacement, path)
    return path


def referrer_host(value: Any) -> str:
    host = (urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")
    own = (urlparse(settings.SITE_URL).hostname or "").lower().removeprefix("www.")
    return "" if not host or host == own else host[:120]


def visitor_hash(ip: str, ua: str, day: date) -> str:
    """Same person + browser on the same day gives the same value; nothing more can be learned from it."""
    raw = f"{settings.SECRET_KEY}:{day.isoformat()}:{ip}:{ua}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


class CollectView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        key = settings.ANALYTICS_KEY
        if not key and not settings.DEBUG:
            return Response({"detail": "Analytics isn't configured."}, status=503)
        if key and not hmac.compare_digest(request.headers.get("X-Analytics-Key", ""), key):
            return Response({"detail": "Invalid analytics key."}, status=403)

        data = request.data if isinstance(request.data, dict) else {}
        kind = data.get("type", "view")

        if kind == "leave":  # time on the page and how far down it they got, sent as the visitor moves on
            try:
                seconds = min(MAX_DURATION, max(0, int(data.get("seconds", 0))))
                scroll = min(100, max(0, int(data.get("scroll", 0))))
                hit_id = int(data.get("id", 0))
            except (TypeError, ValueError):
                return Response(status=400)
            Hit.objects.filter(id=hit_id, session=text(data.get("session"), 32), kind=Hit.Kind.VIEW).update(
                duration=seconds, scroll=Greatest("scroll", Value(scroll))
            )
            return Response(status=204)

        ua = text(data.get("ua"), 400)
        if not ua or BOT.search(ua):
            return Response(status=204)
        if kind == "event" and data.get("name") not in EVENTS:
            return Response({"detail": "Unknown event."}, status=400)
        if kind not in ("view", "event"):
            return Response({"detail": "Unknown type."}, status=400)

        country = text(data.get("country"), 2).upper()
        device, browser, os_name = parse_user_agent(ua)
        now = timezone.now()
        hit = Hit.objects.create(
            created_at=now,
            kind=kind,
            name=text(data.get("name"), 40) if kind == "event" else "",
            target=text(data.get("target"), 120) if kind == "event" else "",
            returning=data.get("returning") is True,
            path=clean_path(data.get("path")),
            referrer=referrer_host(data.get("referrer")),
            source=text(data.get("source"), 60).lower(),
            country=country if re.fullmatch(r"[A-Z]{2}", country) and country not in ("XX", "T1") else "",
            region=text(data.get("region"), 64),
            city=text(data.get("city"), 80),
            device=device,
            browser=browser,
            os=os_name,
            language=text(data.get("language"), 8).split("-")[0].lower(),
            visitor=visitor_hash(text(data.get("ip"), 64), ua, now.date()),
            session=text(data.get("session"), 32),
        )
        return Response({"id": hit.id}, status=201)


# ---------- reporting ----------


class AnalyticsReportView(AdminAPIView):
    def get(self, request):
        try:
            days = min(365, max(1, int(request.query_params.get("days", 30))))
        except ValueError:
            days = 30
        try:
            tz = ZoneInfo(request.query_params.get("tz") or settings.TIME_ZONE)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo(settings.TIME_ZONE)
        filters = {
            name: str(request.query_params[name])[:200] for name in report.FILTERS if request.query_params.get(name)
        }
        return Response(report.build(days, tz, filters))
