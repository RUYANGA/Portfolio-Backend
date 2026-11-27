"""
CV content edited in the dashboard: validation, and the first draft.

The structure is documented in resume_pdf.py. The first draft is the current CV (seed/resume.json)
when it exists, otherwise it is built from the portfolio, so editing never starts from a blank page.
"""

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Certification, Education, Experience, Profile, Project, SkillGroup, split_commas, split_lines
from .resume_pdf import SECTIONS, TITLES

SEED_FILE = Path(settings.BASE_DIR) / "seed" / "resume.json"

BASICS = {
    "name": 120,
    "title": 160,
    "location": 120,
    "phone": 40,
    "email": 254,
    "website": 200,
    "github": 200,
    "linkedin": 200,
}
# List sections: each entry's fields and their maximum lengths ("bullets" is a list of lines).
ENTRIES: dict[str, dict[str, int]] = {
    "skills": {"group": 80, "items": 600},
    "experience": {"role": 120, "company": 120, "location": 120, "period": 60, "bullets": 500},
    "projects": {"name": 120, "subtitle": 160, "link": 300, "bullets": 500, "tech": 300},
    "education": {"degree": 160, "school": 200, "period": 60, "coursework": 600},
    "certifications": {"name": 200, "issuer": 120, "year": 20},
    "extra": {"title": 60, "bullets": 500},
}
LABELS = {**TITLES, "extra": "Extra sections"}
MAX_ENTRIES = 30
MAX_BULLETS = 15
MAX_SUMMARY = 2500


def _text(value: Any, limit: int, where: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)):
        raise ValidationError(f"{where} must be text.")
    text = str(value).strip()
    if len(text) > limit:
        raise ValidationError(f"{where} is too long ({len(text)} characters, at most {limit}).")
    return text


def _lines(value: Any, limit: int, where: str) -> list[str]:
    if isinstance(value, str):
        value = value.splitlines()
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{where} must be a list of lines.")
    if len(value) > MAX_BULLETS:
        raise ValidationError(f"{where}: at most {MAX_BULLETS} bullet points.")
    return [line for line in (_text(v, limit, where) for v in value) if line]


def _entries(section: str, items: Any) -> list[dict[str, Any]]:
    label = LABELS[section]
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValidationError(f"{label} must be a list.")
    if len(items) > MAX_ENTRIES:
        raise ValidationError(f"{label}: at most {MAX_ENTRIES} entries.")
    cleaned = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"{label} entry {index} is invalid.")
        where = f"{label}, entry {index}"
        row: dict[str, Any] = {}
        for field, limit in ENTRIES[section].items():
            if field == "bullets":
                row[field] = _lines(item.get(field), limit, f"{where}, bullet points")
            else:
                row[field] = _text(item.get(field), limit, f"{where}, {field}")
        if any(row.values()):  # completely empty entries are dropped
            cleaned.append(row)
    return cleaned


def clean_content(data: Any) -> dict[str, Any]:
    """Validate and normalise content sent by the dashboard. Unknown keys are dropped."""
    if not isinstance(data, dict):
        raise ValidationError("The CV must be an object.")
    basics_in = data.get("basics") or {}
    if not isinstance(basics_in, dict):
        raise ValidationError("Contact details must be an object.")
    basics = {key: _text(basics_in.get(key), limit, key.capitalize()) for key, limit in BASICS.items()}
    if not basics["name"]:
        raise ValidationError("Your name is required.")

    content: dict[str, Any] = {
        "basics": basics,
        "summary": _text(data.get("summary"), MAX_SUMMARY, "Professional summary"),
        "competencies": _lines(data.get("competencies"), 300, "Core competencies"),
    }
    for section in ENTRIES:
        content[section] = _entries(section, data.get(section))

    order = [key for key in data.get("order") or [] if key in SECTIONS]
    content["order"] = list(dict.fromkeys(order + [key for key in SECTIONS if key not in order]))
    content["hidden"] = [key for key in dict.fromkeys(data.get("hidden") or []) if key in SECTIONS]
    titles = data.get("titles") or {}
    if not isinstance(titles, dict):
        raise ValidationError("Section titles must be an object.")
    content["titles"] = {k: _text(v, 60, f"Title of {k}") for k, v in titles.items() if k in TITLES and v}
    return content


def _social(profile: Profile | None, needle: str) -> str:
    if profile:
        for link in profile.socials.all():
            if needle in link.url.lower() or needle in link.label.lower():
                return link.url
    return ""


def from_portfolio() -> dict[str, Any]:
    """A draft built from the portfolio's profile, experience, projects, skills and education."""
    profile = Profile.objects.first()
    projects = list(Project.objects.filter(featured=True)) or list(Project.objects.all())
    return clean_content(
        {
            "basics": {
                "name": profile.name if profile else "Your name",
                "title": profile.title if profile else "",
                "location": profile.location if profile else "",
                "phone": profile.phone if profile else "",
                "email": profile.email if profile else "",
                "website": settings.SITE_URL,
                "github": _social(profile, "github"),
                "linkedin": _social(profile, "linkedin"),
            },
            "summary": profile.summary if profile else "",
            "skills": [{"group": g.name, "items": ", ".join(g.skill_list)} for g in SkillGroup.objects.all()],
            "experience": [
                {
                    "role": job.role,
                    "company": job.company,
                    "location": job.location,
                    "period": job.period,
                    "bullets": split_lines(job.highlights) or ([job.summary] if job.summary else []),
                }
                for job in Experience.objects.all()
            ],
            "projects": [
                {
                    "name": p.title,
                    "subtitle": p.tagline,
                    "link": p.url or p.repo_url,
                    "bullets": [],
                    "tech": ", ".join(split_commas(p.stack)),
                }
                for p in projects[:4]
            ],
            "education": [
                {"degree": e.degree, "school": e.institution, "period": e.period, "coursework": e.coursework}
                for e in Education.objects.all()
            ],
            "certifications": [{"name": c.name, "issuer": "", "year": c.year} for c in Certification.objects.all()],
        }
    )


def first_draft() -> dict[str, Any]:
    """The current CV's content when it's in the seed, otherwise a draft from the portfolio."""
    if SEED_FILE.exists():
        try:
            return clean_content(json.loads(SEED_FILE.read_text(encoding="utf-8")))
        except (ValueError, ValidationError):
            pass
    return from_portfolio()
