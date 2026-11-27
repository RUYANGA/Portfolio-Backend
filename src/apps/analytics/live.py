"""
Live analytics over WebSocket: wss://<api>/ws/analytics/?ticket=…

- The collector publishes every page view, action and departure with PostgreSQL NOTIFY, so every
  server process sees it without Redis or any other service.
- The dashboard asks /api/admin/analytics/live-ticket/ (staff token) for a one-minute signed
  ticket, then connects here; the session token itself never reaches the browser.
- Each connection LISTENs, forwards events as they happen, and sends a presence snapshot
  (who is on the site right now) every few seconds, so departures without a "leave" show up too.
"""

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

import psycopg
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection
from django.utils import timezone

from . import report

log = logging.getLogger("apps.analytics.live")

CHANNEL = "analytics"
TICKET_SALT = "analytics-live"
TICKET_SECONDS = 60
PRESENCE_EVERY = 5  # seconds between presence snapshots
MAX_PAYLOAD = 7000  # NOTIFY payloads must stay under 8000 bytes

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


# ---------- publishing (sync, called from the collector) ----------


def publish(event: dict[str, Any]) -> None:
    """Tell every live dashboard about an event. Never breaks collecting if it fails."""
    payload = json.dumps(event, default=str)
    if len(payload) > MAX_PAYLOAD:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_notify(%s, %s)", [CHANNEL, payload])
    except Exception:  # noqa: BLE001 - live updates are best effort
        log.warning("Couldn't publish a live analytics event", exc_info=True)


# ---------- tickets ----------


def make_ticket(user_id: int) -> str:
    return signing.dumps({"u": user_id}, salt=TICKET_SALT)


def ticket_user(ticket: str) -> int | None:
    """The staff user a ticket was issued to, if it's genuine, fresh and they're still staff."""
    try:
        data = signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_SECONDS)
    except signing.BadSignature:
        return None
    user = get_user_model().objects.filter(pk=data.get("u"), is_active=True, is_staff=True).first()
    return user.pk if user else None


def socket_url(request) -> str:
    base = settings.PUBLIC_URL or request.build_absolute_uri("/").rstrip("/")
    return re.sub(r"^http", "ws", base, count=1) + "/ws/analytics/"


def origin_allowed(origin: str) -> bool:
    """Only the site (and its dashboard) may open the socket."""
    if not origin:
        return False
    if origin in settings.CORS_ALLOWED_ORIGINS:
        return True
    if any(re.match(pattern, origin) for pattern in settings.CORS_ALLOWED_ORIGIN_REGEXES):
        return True
    return bool(settings.DEBUG and re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", origin))


# ---------- the socket ----------


def presence_snapshot() -> dict[str, Any]:
    return {"type": "presence", **report.live(timezone.now())}


def conninfo() -> str:
    db = settings.DATABASES["default"]
    return psycopg.conninfo.make_conninfo(
        dbname=db.get("NAME") or "",
        user=db.get("USER") or None,
        password=db.get("PASSWORD") or None,
        host=db.get("HOST") or None,
        port=str(db.get("PORT") or "") or None,
    )


async def listen(queue: "asyncio.Queue[str]") -> None:
    """Forward every NOTIFY on the analytics channel into the queue, reconnecting if needed."""
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(conninfo(), autocommit=True) as conn:
                await conn.execute(f"LISTEN {CHANNEL}")
                async for notice in conn.notifies():
                    await queue.put(notice.payload)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Live analytics listener lost the database; retrying", exc_info=True)
            await asyncio.sleep(3)


async def send_json(send: Send, data: dict[str, Any]) -> None:
    await send({"type": "websocket.send", "text": json.dumps(data, default=str)})


async def analytics_socket(scope: Scope, receive: Receive, send: Send) -> None:
    message = await receive()
    if message.get("type") != "websocket.connect":
        return
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    ticket = parse_qs(scope.get("query_string", b"").decode()).get("ticket", [""])[0]
    if not origin_allowed(headers.get("origin", "")) or not await sync_to_async(ticket_user)(ticket):
        await send({"type": "websocket.close", "code": 4403})  # the dashboard fetches a new ticket
        return
    await send({"type": "websocket.accept"})

    queue: asyncio.Queue[str] = asyncio.Queue()
    listener = asyncio.create_task(listen(queue))
    closed = asyncio.Event()

    async def watch_client() -> None:
        while True:
            incoming = await receive()
            if incoming.get("type") == "websocket.disconnect":
                closed.set()
                return

    watcher = asyncio.create_task(watch_client())
    try:
        await send_json(send, await sync_to_async(presence_snapshot)())
        loop = asyncio.get_running_loop()
        next_presence = loop.time() + PRESENCE_EVERY
        while not closed.is_set():
            timeout = max(0.0, next_presence - loop.time())
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                await send_json(send, await sync_to_async(presence_snapshot)())
                next_presence = loop.time() + PRESENCE_EVERY
                continue
            await send({"type": "websocket.send", "text": payload})
            if json.loads(payload).get("type") in ("view", "leave"):  # someone arrived or left
                await send_json(send, await sync_to_async(presence_snapshot)())
                next_presence = loop.time() + PRESENCE_EVERY
    except Exception:  # noqa: BLE001 - the client is gone or the socket broke
        pass
    finally:
        listener.cancel()
        watcher.cancel()
