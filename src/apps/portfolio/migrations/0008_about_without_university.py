"""
Stops the site presenting the owner as a current student, while keeping the University of Rwanda
as where the Bachelor of Science in Computer Science is from:

- About: drops the opening "I am a … at the University of Rwanda, and most of what I know…"
  (→ "Most of what I know…").
- Education: "BSc in Computer Science" is written out in full, and dates that read as still
  studying ("Final year", "2023-2027") are removed.

Only these exact known values are changed, so text written differently in the dashboard is left alone.
"""

from django.db import migrations

ABOUT_OPENINGS = [
    "I am a final-year Computer Science student at the University of Rwanda, and most of what I know",
    "I am a Computer Scientist at the University of Rwanda, and most of what I know",
]
STUDENT_PERIODS = {"final year", "2023-2027", "2023 - 2027", "2023 – 2027", "2023–2027"}


def forwards(apps, schema_editor):
    Profile = apps.get_model("portfolio", "Profile")
    for profile in Profile.objects.all():
        for opening in ABOUT_OPENINGS:
            if profile.about.startswith(opening):
                profile.about = "Most of what I know" + profile.about[len(opening) :]
                profile.save(update_fields=["about"])
                break

    Education = apps.get_model("portfolio", "Education")
    for entry in Education.objects.filter(institution__icontains="University of Rwanda"):
        if entry.degree == "BSc in Computer Science":
            entry.degree = "Bachelor of Science in Computer Science"
        if entry.period.strip().lower() in STUDENT_PERIODS:
            entry.period = ""
        entry.save(update_fields=["degree", "period"])


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0007_resume")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
