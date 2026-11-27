"""
Adds the VONSUNG internship (Django Full-Stack Intern, Apr – Jun 2026) to Experience and to the CV
draft, placed after AmaliTech so the list stays in date order.

Nothing is added if a VONSUNG entry already exists, so it can't be duplicated. On a fresh install
the seed adds it instead (seed/portfolio.json and seed/resume.json include it).
"""

from django.db import migrations

ROLE = "Django Full-Stack Intern"
COMPANY = "VONSUNG"
LOCATION = "Kigali, Rwanda (Hybrid)"
PERIOD = "Apr 2026 – Jun 2026"
HIGHLIGHTS = [
    "Built full-stack web features with Django, from data models and views to server-rendered templates.",
    "Developed REST APIs with Django REST Framework and connected them to the frontend.",
    "Designed PostgreSQL data models and implemented authentication and role-based access.",
    "Worked in a hybrid team, taking part in code reviews, testing and Git-based delivery.",
]
SUMMARY = "Full-stack web development with Django and Django REST Framework in a hybrid team."
TECHNOLOGIES = "Python, Django, Django REST Framework, PostgreSQL, JavaScript"


def add_experience(apps):
    Experience = apps.get_model("portfolio", "Experience")
    jobs = list(Experience.objects.order_by("order", "id"))
    # Already there, or a fresh install (the seed adds it, in order, from seed/portfolio.json).
    if not jobs or any(job.company.lower() == COMPANY.lower() for job in jobs):
        return
    after = next((i for i, job in enumerate(jobs) if job.company.lower() == "amalitech"), None)
    position = after + 1 if after is not None else len(jobs)
    new = Experience(
        role=ROLE,
        company=COMPANY,
        location=LOCATION,
        period=PERIOD,
        is_current=False,
        summary=SUMMARY,
        highlights="\n".join(HIGHLIGHTS),
        technologies=TECHNOLOGIES,
    )
    jobs.insert(position, new)
    for order, job in enumerate(jobs):  # renumber so the new entry sits in date order
        job.order = order
        job.save()


def add_to_cv_draft(apps):
    Resume = apps.get_model("portfolio", "Resume")
    for resume in Resume.objects.all():
        jobs = list(resume.content.get("experience") or [])
        if any(job.get("company", "").lower() == COMPANY.lower() for job in jobs):
            continue
        after = next((i for i, job in enumerate(jobs) if job.get("company", "").lower() == "amalitech"), None)
        entry = {"role": ROLE, "company": COMPANY, "location": LOCATION, "period": PERIOD, "bullets": HIGHLIGHTS}
        jobs.insert(after + 1 if after is not None else len(jobs), entry)
        resume.content = {**resume.content, "experience": jobs}
        resume.save(update_fields=["content"])


def forwards(apps, schema_editor):
    add_experience(apps)
    add_to_cv_draft(apps)


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0008_about_without_university")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
