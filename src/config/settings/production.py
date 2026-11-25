"""Production (Docker / gunicorn): debug off, HTTPS-aware, and strict about secrets."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import SECRET_KEY

DEBUG = False

# Refuse to start with a missing or placeholder secret key.
if len(SECRET_KEY) < 32 or "change-me" in SECRET_KEY:
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY to a long random value (50+ characters). "
        'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(50))"'
    )

# Behind an HTTPS reverse proxy (Nginx, Caddy, Coolify…).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
