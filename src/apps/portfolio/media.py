"""Helpers for uploaded files."""

from django.conf import settings


def absolute(request, field):
    """Full URL of an uploaded file, using PUBLIC_URL when set (see settings)."""
    if not field:
        return None
    url = field.url
    if settings.PUBLIC_URL:
        return f"{settings.PUBLIC_URL}{url}"
    return request.build_absolute_uri(url) if request else url
