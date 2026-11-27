"""
ASGI entry point (gunicorn runs it with Uvicorn workers). Defaults to production settings.

HTTP goes to Django as usual; the WebSocket /ws/analytics/ streams live analytics to the dashboard.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django_application = get_asgi_application()

from apps.analytics.live import analytics_socket  # noqa: E402  (needs Django set up first)


async def application(scope, receive, send):
    if scope["type"] == "websocket":
        if scope["path"].rstrip("/") == "/ws/analytics":
            return await analytics_socket(scope, receive, send)
        await receive()
        return await send({"type": "websocket.close", "code": 4404})
    return await django_application(scope, receive, send)
