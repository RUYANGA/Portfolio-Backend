"""
Visitor analytics.

POST /api/analytics/collect/   called by the Next.js site's server (never by browsers directly), with
                               the shared ANALYTICS_KEY. It forwards the visitor's IP, browser and the
                               country/city that Vercel works out from the IP.
GET  /api/admin/analytics/     the dashboard report (?days=1..365&tz=Area/City), staff token required.
"""

import hashlib
import hmac
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Avg, Count, Q, QuerySet
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, TruncDate, TruncHour
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.portfolio.api.admin.auth import AdminAPIView

from .models import Hit

MAX_DURATION = 30 * 60  # a tab left open overnight shouldn't count as hours of reading
LIVE_WINDOW = timedelta(minutes=5)
EVENTS = {"cv_download", "booking", "contact", "project_open", "lab_open", "share", "outbound"}

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

        if kind == "leave":  # time spent on a page, sent when the visitor moves on
            try:
                seconds = min(MAX_DURATION, max(0, int(data.get("seconds", 0))))
                hit_id = int(data.get("id", 0))
            except (TypeError, ValueError):
                return Response(status=400)
            Hit.objects.filter(id=hit_id, session=text(data.get("session"), 32), kind=Hit.Kind.VIEW).update(
                duration=seconds
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


def summary(views: QuerySet) -> dict[str, Any]:
    sessions = list(views.exclude(session="").values("session").annotate(n=Count("id")))
    count = views.count()
    durations = views.filter(duration__gt=0)
    return {
        "views": count,
        "visitors": views.values("visitor").distinct().count(),
        "sessions": len(sessions),
        "views_per_session": round(count / len(sessions), 2) if sessions else 0,
        "bounce_rate": round(100 * sum(1 for s in sessions if s["n"] == 1) / len(sessions), 1) if sessions else 0,
        "avg_time": round(durations.aggregate(avg=Avg("duration"))["avg"] or 0),
    }


def breakdown(views: QuerySet, *fields: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        views.values(*fields)
        .annotate(views=Count("id"), visitors=Count("visitor", distinct=True))
        .order_by("-visitors", "-views")[:limit]
    )
    return list(rows)


def sources(views: QuerySet, limit: int = 10) -> list[dict[str, Any]]:
    seen: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    for source, referrer, visitor in views.values_list("source", "referrer", "visitor"):
        name = source or referrer or "Direct"
        seen[name].add(visitor)
        counts[name] += 1
    ranked = sorted(counts, key=lambda name: (-len(seen[name]), -counts[name]))[:limit]
    return [{"source": name, "views": counts[name], "visitors": len(seen[name])} for name in ranked]


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

        now = timezone.now()
        today = now.astimezone(tz).date()
        start = datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=tz)
        previous_start = start - timedelta(days=days)

        hits = Hit.objects.filter(created_at__gte=start, created_at__lte=now)
        views = hits.filter(kind=Hit.Kind.VIEW)
        previous = Hit.objects.filter(kind=Hit.Kind.VIEW, created_at__gte=previous_start, created_at__lt=start)

        # Views and visitors over time: hourly for "today", daily otherwise (missing days filled with 0).
        if days == 1:
            buckets = {
                row["at"].astimezone(tz).hour: row
                for row in views.annotate(at=TruncHour("created_at", tzinfo=tz))
                .values("at")
                .annotate(views=Count("id"), visitors=Count("visitor", distinct=True))
            }
            series = [
                {
                    "label": f"{hour:02d}:00",
                    "views": buckets.get(hour, {}).get("views", 0),
                    "visitors": buckets.get(hour, {}).get("visitors", 0),
                }
                for hour in range(24)
            ]
        else:
            daily = {
                row["day"]: row
                for row in views.annotate(day=TruncDate("created_at", tzinfo=tz))
                .values("day")
                .annotate(views=Count("id"), visitors=Count("visitor", distinct=True))
            }
            series = []
            for offset in range(days):
                day = start.date() + timedelta(days=offset)
                row = daily.get(day, {})
                series.append(
                    {"label": day.isoformat(), "views": row.get("views", 0), "visitors": row.get("visitors", 0)}
                )

        hours = {
            row["hour"]: row["views"]
            for row in views.annotate(hour=ExtractHour("created_at", tzinfo=tz))
            .values("hour")
            .annotate(views=Count("id"))
        }
        weekdays = {
            row["weekday"]: row["views"]
            for row in views.annotate(weekday=ExtractIsoWeekDay("created_at", tzinfo=tz))
            .values("weekday")
            .annotate(views=Count("id"))
        }

        live = Hit.objects.filter(kind=Hit.Kind.VIEW, created_at__gte=now - LIVE_WINDOW)
        latest_by_session: dict[str, dict[str, Any]] = {}
        for visit in live.order_by("created_at").values("session", "visitor", "path", "country", "city", "device"):
            key = visit["session"] or visit["visitor"]
            latest_by_session[key] = {"path": visit["path"], "country": visit["country"], "city": visit["city"]}
            latest_by_session[key]["device"] = visit["device"]

        pages = list(
            views.values("path")
            .annotate(
                views=Count("id"),
                visitors=Count("visitor", distinct=True),
                avg_time=Avg("duration", filter=Q(duration__gt=0)),
            )
            .order_by("-views")[:15]
        )
        for page in pages:
            page["avg_time"] = round(page["avg_time"] or 0)

        events = hits.filter(kind=Hit.Kind.EVENT)
        return Response(
            {
                "range": {"days": days, "start": start, "end": now, "timezone": str(tz)},
                "totals": summary(views),
                "previous": summary(previous),
                "series": series,
                "countries": breakdown(views, "country", limit=50),
                "cities": breakdown(views.exclude(city=""), "city", "country", limit=15),
                "pages": pages,
                "sources": sources(views),
                "devices": breakdown(views, "device"),
                "browsers": breakdown(views, "browser"),
                "systems": breakdown(views, "os"),
                "languages": breakdown(views.exclude(language=""), "language"),
                "hours": [hours.get(hour, 0) for hour in range(24)],
                "weekdays": [weekdays.get(day, 0) for day in range(1, 8)],
                "events": list(
                    events.values("name")
                    .annotate(count=Count("id"), visitors=Count("visitor", distinct=True))
                    .order_by("-count")
                ),
                "live": {"visitors": len(latest_by_session), "pages": list(latest_by_session.values())[-10:]},
                "recent": list(
                    views.values(
                        "created_at", "path", "country", "city", "device", "browser", "os", "referrer", "duration"
                    )[:25]
                ),
            }
        )
