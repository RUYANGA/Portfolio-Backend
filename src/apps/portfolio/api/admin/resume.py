"""
Dashboard CV builder, under /api/admin/resume/ (staff token required).

GET   resume/                            the draft, what the site shows now, and recent versions
PUT   resume/            {content}       save the draft (doesn't change the site)
POST  resume/preview/    {content}       the draft as a PDF, for the live preview
POST  resume/publish/    {content, note} save, render and make it the site's CV (a new version)
POST  resume/versions/<n>/restore/       load a published version back into the draft
GET   resume/import/                     a draft built from the portfolio (to refill sections)
"""

import re

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse
from rest_framework import exceptions
from rest_framework.response import Response

from apps.portfolio.media import absolute
from apps.portfolio.models import Profile, Resume, ResumeVersion
from apps.portfolio.resume_content import clean_content, first_draft, from_portfolio
from apps.portfolio.resume_pdf import render

from .auth import AdminAPIView

RECENT_VERSIONS = 20


def content_from(request) -> dict:
    data = request.data if isinstance(request.data, dict) else {}
    try:
        return clean_content(data.get("content"))
    except ValidationError as exc:
        raise exceptions.ValidationError({"detail": " ".join(exc.messages)})


def file_name(name: str) -> str:
    """ "Merci Ruyanga" -> "Merci_Ruyanga_CV.pdf", like the original upload."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "CV"
    return f"{safe}_CV.pdf"


def payload(request) -> dict:
    resume = Resume.objects.first()
    profile = Profile.objects.first()
    versions = list(ResumeVersion.objects.all()[:RECENT_VERSIONS])
    latest = versions[0] if versions else None
    live_name = profile.cv_file.name if profile and profile.cv_file else ""
    live_version = next((v for v in versions if v.file.name == live_name), None) if live_name else None
    content = resume.content if resume and resume.content else first_draft()
    return {
        "content": content,
        "saved_at": resume.updated_at if resume else None,
        "unpublished": latest is None or latest.content != content,
        "live": {
            # "builder": a version published here; "upload": a PDF uploaded under Profile; "none".
            "source": "builder" if live_version else ("upload" if live_name else "none"),
            "version": live_version.number if live_version else None,
            "url": absolute(request, profile.cv_file) if profile else None,
        },
        "versions": [
            {
                "number": v.number,
                "note": v.note,
                "created_at": v.created_at,
                "url": absolute(request, v.file),
                "live": v is live_version,
            }
            for v in versions
        ],
    }


class ResumeView(AdminAPIView):
    def get(self, request):
        return Response(payload(request))

    def put(self, request):
        content = content_from(request)
        resume = Resume.objects.first() or Resume()
        resume.content = content
        resume.save()
        return Response(payload(request))


class ResumePreviewView(AdminAPIView):
    def post(self, request):
        pdf = render(content_from(request))
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="preview.pdf"'
        response["Cache-Control"] = "no-store"
        return response


class ResumePublishView(AdminAPIView):
    def post(self, request):
        content = content_from(request)
        profile = Profile.objects.first()
        if profile is None:
            raise exceptions.ValidationError({"detail": "Create your profile first."})
        note = str((request.data or {}).get("note") or "").strip()[:200]
        pdf = render(content)
        with transaction.atomic():
            resume = Resume.objects.select_for_update().first() or Resume()
            resume.content = content
            resume.save()
            number = (ResumeVersion.objects.aggregate(top=Max("number"))["top"] or 0) + 1
            version = ResumeVersion(number=number, content=content, note=note)
            version.file.save(file_name(content["basics"]["name"]), ContentFile(pdf), save=False)
            version.save()
            # The site's CV is this version's file; earlier files stay available in the history.
            profile.cv_file.name = version.file.name
            profile.save(update_fields=["cv_file", "updated_at"])
        return Response(payload(request), status=201)


class ResumeRestoreView(AdminAPIView):
    def post(self, request, number: int):
        version = ResumeVersion.objects.filter(number=number).first()
        if version is None:
            raise exceptions.NotFound("That version doesn't exist.")
        resume = Resume.objects.first() or Resume()
        resume.content = version.content
        resume.save()
        return Response(payload(request))


class ResumeImportView(AdminAPIView):
    def get(self, request):
        return Response({"content": from_portfolio()})
