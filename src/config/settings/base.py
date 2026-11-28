"""
Settings shared by every environment. Values come from environment variables (or backend/.env).

Pick an environment with DJANGO_SETTINGS_MODULE:
  config.settings.development   manage.py default
  config.settings.production    Docker / gunicorn default
  config.settings.test          used automatically by `manage.py test`
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# backend/src/config/settings/base.py → parents[2] is backend/src, parents[3] is backend/
SRC_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = SRC_DIR.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=""):
    return os.getenv(name, default)


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# ---------- Core ----------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    # Local
    "apps.portfolio",
    "apps.booking",
    "apps.analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------- Database ----------
# PostgreSQL via DATABASE_URL; falls back to SQLite when it's empty.
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------- Internationalisation ----------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kigali"
USE_I18N = True
USE_TZ = True

# ---------- Static and uploaded files ----------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
# Public address of this API, e.g. https://api.example.com. Used for image and file links,
# so they work in browsers even when the site's server reaches the API by an internal name.
PUBLIC_URL = env("PUBLIC_URL").rstrip("/")
# Serve uploaded files from Django (fine for a portfolio's traffic).
# Set to false if a reverse proxy or CDN serves /media/ instead.
SERVE_MEDIA = env_bool("SERVE_MEDIA", True)
# Starting content loaded by `manage.py seed_portfolio`.
SEED_DIR = BASE_DIR / "seed"

# ---------- API ----------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
# Optional regex patterns, e.g. ^https://merci-portfolio-[a-z0-9-]+\.vercel\.app$ for Vercel previews.
CORS_ALLOWED_ORIGIN_REGEXES = env_list("CORS_ALLOWED_ORIGIN_REGEXES")

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_THROTTLE_RATES": {"contact": "5/hour", "admin_login": "20/hour", "booking": "5/hour"},
}

# The admin dashboard lives in the Next.js app and talks to /api/admin/.
ADMIN_TOKEN_TTL = int(env("ADMIN_TOKEN_TTL", str(7 * 24 * 3600)))  # seconds a sign-in stays valid
# Django's built-in admin is off by default; set DJANGO_ADMIN_ENABLED=true for emergency access.
DJANGO_ADMIN_ENABLED = env_bool("DJANGO_ADMIN_ENABLED", False)

# ---------- Email (contact-form notifications, optional) ----------
# Leave EMAIL_HOST empty to only store messages (and print them to the console).
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER or "noreply@localhost"
CONTACT_NOTIFY_EMAIL = env("CONTACT_NOTIFY_EMAIL")
# Public address of the Next.js site, e.g. https://merci.dev. The notification email links to
# the dashboard inbox there. Defaults to the first CORS origin, which is usually the site.
# Shared secret between the Next.js site and this API for visitor analytics (any long random string,
# set to the same value on both). Without it, analytics only works with DEBUG on.
ANALYTICS_KEY = env("ANALYTICS_KEY")
SITE_URL = (env("SITE_URL") or next(iter(CORS_ALLOWED_ORIGINS), "")).rstrip("/")
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST else "django.core.mail.backends.console.EmailBackend"
)

# ---------- Meeting booking ----------
# Private iCal addresses of the calendars whose busy time blocks bookings, comma-separated
# (e.g. Google Calendar's "secret address in iCal format" and an Outlook published-calendar ICS
# link). They are secrets: anyone with the link can read the calendar, so keep them in .env only.
# Quotes and spaces pasted along with the links (common in hosting dashboards) are ignored.
BOOKING_BUSY_CALENDARS = [
    url.strip().strip("\"'").strip().replace("webcal://", "https://", 1)
    for url in env_list("BOOKING_BUSY_CALENDARS")
    if url.strip().strip("\"'").strip()
]
# How often each calendar is read again: changes appear on the booking page within this many seconds.
BOOKING_CALENDAR_REFRESH_SECONDS = int(env("BOOKING_CALENDAR_REFRESH_SECONDS", "60"))

# --- Video meeting providers (optional) ---------------------------------------
# Google Meet: create a Google Cloud OAuth client (Desktop) with Calendar API enabled, then obtain
# a refresh token for the calendar owner. Set the calendar ID (usually the owner's email).
GOOGLE_CALENDAR_CLIENT_ID = env("GOOGLE_CALENDAR_CLIENT_ID", "")
GOOGLE_CALENDAR_CLIENT_SECRET = env("GOOGLE_CALENDAR_CLIENT_SECRET", "")
GOOGLE_CALENDAR_REFRESH_TOKEN = env("GOOGLE_CALENDAR_REFRESH_TOKEN", "")
GOOGLE_CALENDAR_ID = env("GOOGLE_CALENDAR_ID", "primary")

# Microsoft Teams: Azure app registration with OnlineMeetings.ReadWrite.All application permission
# and admin consent. MICROSOFT_USER_ID is the organizer's user id or UPN.
MICROSOFT_TENANT_ID = env("MICROSOFT_TENANT_ID", "")
MICROSOFT_CLIENT_ID = env("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = env("MICROSOFT_CLIENT_SECRET", "")
MICROSOFT_USER_ID = env("MICROSOFT_USER_ID", "")

# ---------- Logging (to stdout, so Docker collects it) ----------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.server": {"level": "WARNING"}},
}
