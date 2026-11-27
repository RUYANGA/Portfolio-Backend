"""
Publishes the CV with the VONSUNG internship, so the résumé visitors open from the site includes it.

The new version is the CV that is live now plus VONSUNG (after AmaliTech), not the dashboard
draft, so unpublished draft edits are never made public. Nothing happens if the live CV already
has VONSUNG, or if there's no profile yet.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import migrations

VONSUNG = {
    "role": "Django Full-Stack Intern",
    "company": "VONSUNG",
    "location": "Kigali, Rwanda (Hybrid)",
    "period": "Apr 2026 – Jun 2026",
    "bullets": [
        "Built full-stack web features with Django, from data models and views to server-rendered templates.",
        "Developed REST APIs with Django REST Framework and connected them to the frontend.",
        "Designed PostgreSQL data models and implemented authentication and role-based access.",
        "Worked in a hybrid team, taking part in code reviews, testing and Git-based delivery.",
    ],
}


def with_vonsung(content):
    jobs = list(content.get("experience") or [])
    if any(job.get("company", "").lower() == "vonsung" for job in jobs):
        return content
    after = next((i for i, job in enumerate(jobs) if job.get("company", "").lower() == "amalitech"), None)
    jobs.insert(after + 1 if after is not None else len(jobs), VONSUNG)
    return {**content, "experience": jobs}


def forwards(apps, schema_editor):
    from apps.portfolio.resume_content import clean_content
    from apps.portfolio.resume_pdf import render

    Profile = apps.get_model("portfolio", "Profile")
    ResumeVersion = apps.get_model("portfolio", "ResumeVersion")
    profile = Profile.objects.first()
    if profile is None:
        return

    live = ResumeVersion.objects.filter(file=profile.cv_file.name).first() if profile.cv_file else None
    if live is not None:
        base = live.content  # the CV published from the dashboard
        if with_vonsung(base) == base:
            return  # already includes VONSUNG
    else:
        seed = Path(settings.BASE_DIR) / "seed" / "resume.json"
        if not seed.exists():
            return
        base = json.loads(seed.read_text(encoding="utf-8"))  # the original uploaded CV's content

    content = clean_content(with_vonsung(base))
    number = (ResumeVersion.objects.order_by("-number").values_list("number", flat=True).first() or 0) + 1
    name = "_".join(content["basics"]["name"].split()) or "CV"
    path = default_storage.save(f"cv/v{number}/{name}_CV.pdf", ContentFile(render(content)))
    ResumeVersion.objects.create(number=number, content=content, file=path, note="Added VONSUNG internship")
    profile.cv_file.name = path
    profile.save(update_fields=["cv_file"])


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0009_vonsung_experience")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
