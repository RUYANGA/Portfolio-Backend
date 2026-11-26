"""
More meeting types for the booking page, covering the usual reasons people want to talk:
hiring, freelance work, reviews, mentoring and community.

Matched on slug: existing types (and any edits made in the dashboard) are left untouched,
and a type deleted in the dashboard isn't created again on later migrations.
"""

from django.db import migrations

NEW_TYPES = [
    (
        "Job interview",
        "job-interview",
        60,
        "A formal interview for a full-time or contract role, with your team or hiring panel.",
    ),
    (
        "Technical interview",
        "technical-interview",
        60,
        "Live coding, system design or a walkthrough of a take-home task.",
    ),
    (
        "Project consultation",
        "project-consultation",
        45,
        "Talk through a system you want built: goals, scope, timeline and the right approach.",
    ),
    (
        "Architecture & code review",
        "architecture-review",
        60,
        "A review of an existing codebase, API or AWS setup, with concrete improvements.",
    ),
    (
        "Mentorship session",
        "mentorship",
        30,
        "Guidance on backend engineering, cloud or your career, for students and junior developers.",
    ),
    (
        "Quick question",
        "quick-question",
        15,
        "A short call for one focused question.",
    ),
    (
        "Collaboration & speaking",
        "collaboration",
        30,
        "Talks, workshops, open-source work or community collaborations.",
    ),
]


def add_types(apps, schema_editor):
    MeetingType = apps.get_model("booking", "MeetingType")
    last = MeetingType.objects.order_by("-order").values_list("order", flat=True).first() or 0
    for offset, (title, slug, minutes, description) in enumerate(NEW_TYPES, start=1):
        MeetingType.objects.get_or_create(
            slug=slug,
            defaults={"title": title, "duration_minutes": minutes, "description": description, "order": last + offset},
        )


def remove_types(apps, schema_editor):
    MeetingType = apps.get_model("booking", "MeetingType")
    MeetingType.objects.filter(slug__in=[slug for _, slug, _, _ in NEW_TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [("booking", "0001_initial")]

    operations = [migrations.RunPython(add_types, remove_types)]
