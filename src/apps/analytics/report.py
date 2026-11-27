"""
The analytics dashboard report.

Everything is computed per visit (a browsing session): hits in the range are grouped by session,
filters keep or drop whole visits, and every figure is then derived from the visits that remain.
A portfolio gets thousands of hits, not millions, so this is done in Python for clarity.

Filters (query string): country, city, device, browser, os, language, source (where the visit came
from: utm_source, referring site or "Direct") and page (visits that included this page).
"""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from .models import Hit

ATTRIBUTE_FILTERS = ("country", "city", "device", "browser", "os", "language")
FILTERS = (*ATTRIBUTE_FILTERS, "source", "page")
SECTIONS = ("about", "experience", "projects", "labs", "skills", "contact")
ACTIONS = {"cv_download", "contact", "booking"}
EXPLORE_EVENTS = {"lab_open", "project_open"}
ENGAGED_SECONDS = 30
ENGAGED_SCROLL = 50
# A visitor is live while their page keeps sending heartbeats (every 15 s): three missed = gone.
LIVE_WINDOW = timedelta(seconds=45)
# Views from tracker versions without heartbeats count as live for 5 minutes (rollout only).
LEGACY_LIVE_WINDOW = timedelta(minutes=5)
FIELDS = (
    "created_at",
    "kind",
    "name",
    "target",
    "path",
    "referrer",
    "source",
    "country",
    "city",
    "device",
    "browser",
    "os",
    "language",
    "visitor",
    "session",
    "duration",
    "scroll",
    "returning",
)

Row = dict[str, Any]


class Visit:
    """One browsing session: its page views and events, in order."""

    def __init__(self, key: str):
        self.key = key
        self.views: list[Row] = []
        self.events: list[Row] = []

    @property
    def entry(self) -> Row:
        return self.views[0]

    @property
    def source(self) -> str:
        return self.entry["source"] or self.entry["referrer"] or "Direct"

    @property
    def visitor(self) -> str:
        return self.entry["visitor"]

    @property
    def time(self) -> int:
        return sum(v["duration"] for v in self.views)

    @property
    def returning(self) -> bool:
        return any(v["returning"] for v in self.views)

    def did(self, *names: str) -> bool:
        return any(e["name"] in names for e in self.events)

    def saw_section(self, *sections: str) -> bool:
        return any(e["name"] == "section" and e["target"] in sections for e in self.events)

    @property
    def engaged(self) -> bool:
        return (
            len(self.views) > 1
            or self.time >= ENGAGED_SECONDS
            or max(v["scroll"] for v in self.views) >= ENGAGED_SCROLL
            or self.did(*ACTIONS, *EXPLORE_EVENTS, "outbound")
        )

    @property
    def explored(self) -> bool:
        return (
            any(v["path"].startswith("/projects/") for v in self.views)
            or self.saw_section("projects", "labs")
            or self.did(*EXPLORE_EVENTS)
        )

    def matches(self, filters: dict[str, str]) -> bool:
        for field in ATTRIBUTE_FILTERS:
            if field in filters and self.entry[field] != filters[field]:
                return False
        if "source" in filters and self.source != filters["source"]:
            return False
        if "page" in filters and not any(v["path"] == filters["page"] for v in self.views):
            return False
        return True


def load_visits(start: datetime, end: datetime, filters: dict[str, str]) -> list[Visit]:
    visits: dict[str, Visit] = {}
    rows = Hit.objects.filter(created_at__gte=start, created_at__lt=end).order_by("created_at").values(*FIELDS)
    for row in rows:
        key = row["session"] or f"visitor:{row['visitor']}"
        visit = visits.setdefault(key, Visit(key))
        (visit.views if row["kind"] == Hit.Kind.VIEW else visit.events).append(row)
    # A visit needs at least one page view (events alone can't say where it came from).
    return [v for v in visits.values() if v.views and v.matches(filters)]


def all_views(visits: Iterable[Visit]) -> Iterable[Row]:
    for visit in visits:
        yield from visit.views


def percent(part: int | float, whole: int | float) -> float:
    return round(100 * part / whole, 1) if whole else 0


def summary(visits: list[Visit]) -> dict[str, Any]:
    views = [v for visit in visits for v in visit.views]
    timed = [v["duration"] for v in views if v["duration"]]
    sessions = len(visits)
    return {
        "views": len(views),
        "visitors": len({visit.visitor for visit in visits}),
        "sessions": sessions,
        "views_per_session": round(len(views) / sessions, 2) if sessions else 0,
        "bounce_rate": percent(sum(1 for v in visits if len(v.views) == 1), sessions),
        "engagement_rate": percent(sum(1 for v in visits if v.engaged), sessions),
        "returning_rate": percent(sum(1 for v in visits if v.returning), sessions),
        "avg_time": round(sum(timed) / len(timed)) if timed else 0,
        "avg_visit": round(sum(v.time for v in visits) / sessions) if sessions else 0,
        "actions": sum(1 for v in visits if v.did(*ACTIONS)),
    }


def breakdown(visits: list[Visit], key: Callable[[Row], Any], limit: int = 10) -> list[dict[str, Any]]:
    """Views and distinct visitors per value of `key` (empty values left out)."""
    views: Counter = Counter()
    visitors: dict[Any, set[str]] = defaultdict(set)
    for row in all_views(visits):
        value = key(row)
        if value in ("", None) or value == ("", ""):
            continue
        views[value] += 1
        visitors[value].add(row["visitor"])
    ranked = sorted(views, key=lambda value: (-len(visitors[value]), -views[value]))[:limit]
    return [{"value": value, "views": views[value], "visitors": len(visitors[value])} for value in ranked]


def sources(visits: list[Visit]) -> list[dict[str, Any]]:
    """Where visits came from, counted once per visit (by the page they landed on)."""
    rows: dict[str, dict[str, Any]] = {}
    for visit in visits:
        row = rows.setdefault(visit.source, {"source": visit.source, "sessions": 0, "visitors": set(), "engaged": 0})
        row["sessions"] += 1
        row["visitors"].add(visit.visitor)
        row["engaged"] += visit.engaged
    result = [
        {
            "source": r["source"],
            "sessions": r["sessions"],
            "visitors": len(r["visitors"]),
            "engagement_rate": percent(r["engaged"], r["sessions"]),
        }
        for r in rows.values()
    ]
    return sorted(result, key=lambda r: (-r["visitors"], -r["sessions"]))[:15]


def pages(visits: list[Visit]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"views": 0, "visitors": set(), "time": [], "scroll": [], "entries": 0, "exits": 0}
    )
    for visit in visits:
        stats[visit.views[0]["path"]]["entries"] += 1
        stats[visit.views[-1]["path"]]["exits"] += 1
        for view in visit.views:
            page = stats[view["path"]]
            page["views"] += 1
            page["visitors"].add(view["visitor"])
            if view["duration"]:
                page["time"].append(view["duration"])
            if view["scroll"]:
                page["scroll"].append(view["scroll"])
    rows = [
        {
            "path": path,
            "views": s["views"],
            "visitors": len(s["visitors"]),
            "avg_time": round(sum(s["time"]) / len(s["time"])) if s["time"] else 0,
            "avg_scroll": round(sum(s["scroll"]) / len(s["scroll"])) if s["scroll"] else None,
            "entries": s["entries"],
            "exits": s["exits"],
            "exit_rate": percent(s["exits"], s["views"]),
        }
        for path, s in stats.items()
    ]
    return sorted(rows, key=lambda r: -r["views"])[:25]


def funnel(visits: list[Visit]) -> list[dict[str, Any]]:
    steps: list[tuple[str, str, Callable[[Visit], bool]]] = [
        ("visited", "Visited the site", lambda v: True),
        ("engaged", "Engaged", lambda v: v.engaged),
        ("explored", "Explored projects or labs", lambda v: v.explored),
        ("action", "Opened résumé, booked or wrote", lambda v: v.did(*ACTIONS)),
        ("contact", "Booked a call or sent a message", lambda v: v.did("contact", "booking")),
    ]
    remaining = visits
    result = []
    for key, label, test in steps:
        remaining = [v for v in remaining if test(v)]
        result.append({"key": key, "label": label, "sessions": len(remaining)})
    return result


def sections(visits: list[Visit]) -> dict[str, Any]:
    """How far down the home page visits got: share of home-page visits that reached each section."""
    home = [v for v in visits if any(view["path"] == "/" for view in v.views)]
    scrolls = [view["scroll"] for visit in home for view in visit.views if view["path"] == "/" and view["scroll"]]
    return {
        "home_visits": len(home),
        "reached": [{"section": s, "sessions": sum(1 for v in home if v.saw_section(s))} for s in SECTIONS],
        "scroll_depth": [
            {"depth": depth, "share": percent(sum(1 for s in scrolls if s >= depth), len(scrolls))}
            for depth in (25, 50, 75, 100)
        ],
    }


def events(visits: list[Visit]) -> dict[str, Any]:
    counts: Counter = Counter()
    who: dict[str, set[str]] = defaultdict(set)
    links: Counter = Counter()
    link_visitors: dict[str, set[str]] = defaultdict(set)
    for visit in visits:
        for event in visit.events:
            counts[event["name"]] += 1
            who[event["name"]].add(visit.visitor)
            if event["name"] == "outbound" and event["target"]:
                links[event["target"]] += 1
                link_visitors[event["target"]].add(visit.visitor)
    return {
        "events": [{"name": n, "count": c, "visitors": len(who[n])} for n, c in counts.most_common()],
        "outbound": [{"target": t, "clicks": c, "visitors": len(link_visitors[t])} for t, c in links.most_common(15)],
    }


def journeys(visits: list[Visit], limit: int = 30) -> list[dict[str, Any]]:
    """The latest visits, each with its steps in order (pages and actions)."""
    latest = sorted(visits, key=lambda v: max(r["created_at"] for r in v.views + v.events), reverse=True)[:limit]
    result = []
    for visit in latest:
        steps = sorted(visit.views + visit.events, key=lambda r: r["created_at"])[:40]
        entry = visit.entry
        result.append(
            {
                "started": entry["created_at"],
                "ended": steps[-1]["created_at"],
                "time": visit.time,
                "pages": len(visit.views),
                "source": visit.source,
                "returning": visit.returning,
                "engaged": visit.engaged,
                "country": entry["country"],
                "city": entry["city"],
                "device": entry["device"],
                "browser": entry["browser"],
                "os": entry["os"],
                "steps": [
                    {
                        "at": s["created_at"],
                        "type": s["kind"],
                        "path": s["path"],
                        "name": s["name"],
                        "target": s["target"],
                        "duration": s["duration"],
                        "scroll": s["scroll"],
                    }
                    for s in steps
                ],
            }
        )
    return result


def series(visits: list[Visit], start: datetime, days: int, tz: ZoneInfo) -> list[dict[str, Any]]:
    """Views and visitors per hour (one day) or per day; missing buckets are 0."""
    size = 24 if days == 1 else days
    views = [0] * size
    visitors: list[set[str]] = [set() for _ in range(size)]
    for row in all_views(visits):
        local = row["created_at"].astimezone(tz)
        index = local.hour if days == 1 else (local.date() - start.date()).days
        if 0 <= index < size:
            views[index] += 1
            visitors[index].add(row["visitor"])
    if days == 1:
        labels = [f"{hour:02d}:00" for hour in range(24)]
    else:
        labels = [(start.date() + timedelta(days=i)).isoformat() for i in range(days)]
    return [{"label": labels[i], "views": views[i], "visitors": len(visitors[i])} for i in range(size)]


def heatmap(visits: list[Visit], tz: ZoneInfo) -> list[list[int]]:
    """Page views by weekday (Mon..Sun) and hour (0..23), in the viewer's timezone."""
    grid = [[0] * 24 for _ in range(7)]
    for row in all_views(visits):
        local = row["created_at"].astimezone(tz)
        grid[local.weekday()][local.hour] += 1
    return grid


def live(now: datetime) -> dict[str, Any]:
    """Who is on the site right now: one row per open visit, most recently active first."""
    rows = (
        Hit.objects.filter(kind=Hit.Kind.VIEW)
        .filter(
            Q(last_seen__gte=now - LIVE_WINDOW) | Q(last_seen__isnull=True, created_at__gte=now - LEGACY_LIVE_WINDOW)
        )
        .order_by("created_at")
        .values(
            "session",
            "visitor",
            "path",
            "country",
            "city",
            "device",
            "browser",
            "source",
            "referrer",
            "created_at",
            "last_seen",
            "duration",
        )
    )
    latest: dict[str, Row] = {}
    for row in rows:  # later views of the same visit replace earlier ones
        latest[row["session"] or row["visitor"]] = {
            "path": row["path"],
            "country": row["country"],
            "city": row["city"],
            "device": row["device"],
            "browser": row["browser"],
            "source": row["source"] or row["referrer"] or "Direct",
            "since": row["created_at"],
            "seen": row["last_seen"] or row["created_at"],
            "seconds": row["duration"],
        }
    pages = sorted(latest.values(), key=lambda p: p["seen"], reverse=True)
    return {"visitors": len(pages), "pages": pages[:20], "at": now}


def build(days: int, tz: ZoneInfo, filters: dict[str, str]) -> dict[str, Any]:
    now = timezone.now()
    today = now.astimezone(tz).date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=tz)
    previous_start = start - timedelta(days=days)

    visits = load_visits(start, now + timedelta(seconds=1), filters)
    before = load_visits(previous_start, start, filters)

    current_series = series(visits, start, days, tz)
    previous_series = series(before, previous_start, days, tz)
    for point, old in zip(current_series, previous_series):
        point["previous"] = old["views"]

    grid = heatmap(visits, tz)
    activity = events(visits)
    return {
        "range": {"days": days, "start": start, "end": now, "timezone": str(tz)},
        "filters": filters,
        "totals": summary(visits),
        "previous": summary(before),
        "series": current_series,
        "countries": [
            {"country": "" if r["value"] == "?" else r["value"], **_counts(r)}
            for r in breakdown(visits, lambda v: v["country"] or "?", 60)
        ],
        "cities": [
            {"city": r["value"][0], "country": r["value"][1], **_counts(r)}
            for r in breakdown(visits, lambda v: (v["city"], v["country"]) if v["city"] else "", 20)
        ],
        "pages": pages(visits),
        "sources": sources(visits),
        "devices": [{"device": r["value"], **_counts(r)} for r in breakdown(visits, lambda v: v["device"])],
        "browsers": [{"browser": r["value"], **_counts(r)} for r in breakdown(visits, lambda v: v["browser"])],
        "systems": [{"os": r["value"], **_counts(r)} for r in breakdown(visits, lambda v: v["os"])],
        "languages": [{"language": r["value"], **_counts(r)} for r in breakdown(visits, lambda v: v["language"])],
        "visitor_types": {
            "new": sum(1 for v in visits if not v.returning),
            "returning": sum(1 for v in visits if v.returning),
        },
        "funnel": funnel(visits),
        "sections": sections(visits),
        "events": activity["events"],
        "outbound": activity["outbound"],
        "heatmap": grid,
        "hours": [sum(day[hour] for day in grid) for hour in range(24)],
        "weekdays": [sum(day) for day in grid],
        "sessions": journeys(visits),
        "recent": recent(visits),  # used by dashboards older than the journeys view
        "live": live(now),
    }


def recent(visits: list[Visit]) -> list[dict[str, Any]]:
    keys = ("created_at", "path", "country", "city", "device", "browser", "os", "referrer", "duration")
    views = sorted(all_views(visits), key=lambda v: v["created_at"], reverse=True)[:25]
    return [{k: v[k] for k in keys} for v in views]


def _counts(row: dict[str, Any]) -> dict[str, int]:
    return {"views": row["views"], "visitors": row["visitors"]}
