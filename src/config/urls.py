from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, HttpRequest
from django.urls import URLPattern, URLResolver, path, re_path
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.static import serve

urlpatterns: list[URLPattern | URLResolver] = []

# The admin dashboard is the Next.js app at /admin. Django's own admin stays available
# for emergencies only when DJANGO_ADMIN_ENABLED=true.
if settings.DJANGO_ADMIN_ENABLED:
    urlpatterns.insert(0, path("django-admin/", admin.site.urls))


@xframe_options_exempt
def media(request: HttpRequest, path: str) -> FileResponse:
    """Serve an uploaded file. MEDIA_ROOT is read per request, so overrides (tests) apply."""
    return serve(request, path, document_root=str(settings.MEDIA_ROOT))


# Uploaded files (images, résumé). They are public content, so they may be framed by the
# site: the résumé is previewed inside a dialog. API responses keep X-Frame-Options: DENY.
if settings.DEBUG or settings.SERVE_MEDIA:
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", media)]
