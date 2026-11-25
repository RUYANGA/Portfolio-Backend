"""Test run: fast password hashing, plain static storage, quiet logs. Used by `manage.py test`."""

from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-secret-key-not-used-anywhere-else-0123456789"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# The production static manifest only exists after collectstatic.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
LOGGING = {"version": 1, "disable_existing_loggers": False, "root": {"level": "CRITICAL"}}
