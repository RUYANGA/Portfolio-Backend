"""
Load the portfolio content from seed/portfolio.json, with images and the CV from seed/media/.

Modes:
  seed_portfolio            Add anything missing. Existing records are left exactly as they are,
                            so edits made in the admin are never overwritten. Seed images that a record
                            still uses but storage has lost (e.g. an empty media volume) are put back.
                            Safe to run on every start.
  seed_portfolio --update   Also overwrite existing records (and their files) with the seed values.
  seed_portfolio --reset    Delete all portfolio content and load it fresh. Contact messages are kept.

Records are matched on a natural key, so re-running never creates duplicates:
profile (the single record), social link label, skill group name, role + company,
project slug, lab title, degree, certification name, and contact subject label.
"""

import json
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.portfolio.models import (
    Certification,
    ContactSubject,
    Education,
    Experience,
    Lab,
    Profile,
    Project,
    SkillGroup,
    SocialLink,
)

CONTENT_MODELS = (SocialLink, Profile, SkillGroup, Experience, Project, Lab, Education, Certification, ContactSubject)

PROFILE_FIELDS = (
    "name",
    "title",
    "headline",
    "summary",
    "about",
    "location",
    "email",
    "secondary_email",
    "phone",
    "available_for_work",
    "years_experience",
    "availability_text",
    "about_heading",
    "experience_intro",
    "projects_intro",
    "skills_intro",
    "contact_heading",
    "contact_intro",
    "meta_description",
)


class Command(BaseCommand):
    help = "Seed the portfolio content (text, images and CV). Never overwrites admin edits unless --update or --reset."

    def add_arguments(self, parser):
        data_dir = Path(settings.SEED_DIR)
        parser.add_argument("--file", default=str(data_dir / "portfolio.json"), help="Seed data file.")
        parser.add_argument(
            "--media-dir", default=str(data_dir / "media"), help="Folder holding seed images and files."
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--update", action="store_true", help="Overwrite existing records with the seed values.")
        mode.add_argument("--reset", action="store_true", help="Delete all portfolio content first, then load it.")
        parser.add_argument("--noinput", "--no-input", action="store_true", help="Don't ask for confirmation.")

    def handle(self, *args, **options):
        data_file = Path(options["file"])
        if not data_file.exists():
            raise CommandError(f"Seed file not found: {data_file}")
        self.data = json.loads(data_file.read_text(encoding="utf-8"))
        self.media_dir = Path(options["media_dir"])
        self.update = options["update"] or options["reset"]
        self.stats: Counter[str] = Counter()

        if options["reset"] and not options["noinput"]:
            answer = input("This deletes all portfolio content (contact messages are kept). Type 'yes' to continue: ")
            if answer.strip().lower() != "yes":
                raise CommandError("Reset cancelled.")

        with transaction.atomic():
            if options["reset"]:
                for model in CONTENT_MODELS:
                    for obj in model.objects.all():
                        self._delete_files(obj)
                    model.objects.all().delete()

            profile = self.seed_profile()
            self.seed_socials(profile)
            self.seed_skill_groups()
            self.seed_experiences()
            self.seed_projects()
            self.seed_labs()
            self.seed_education()
            self.seed_certifications()
            self.seed_contact_subjects()

        self.report()

    # ---------- Sections ----------

    def seed_profile(self):
        p = self.data["profile"]
        values = {k: p[k] for k in PROFILE_FIELDS if k in p}
        profile = Profile.objects.first()
        if profile is None:
            profile = Profile(**values)
            self._attach(profile, "photo", p.get("photo"))
            self._attach(profile, "cv_file", p.get("cv_file"))
            profile.save()
            self.stats["profile created"] += 1
        elif self.update:
            for k, v in values.items():
                setattr(profile, k, v)
            self._attach(profile, "photo", p.get("photo"), replace=True)
            self._attach(profile, "cv_file", p.get("cv_file"), replace=True)
            profile.save()
            self.stats["profile updated"] += 1
        else:
            self._restore_missing(profile, "photo", p.get("photo"))
            self._restore_missing(profile, "cv_file", p.get("cv_file"))
            self.stats["profile kept"] += 1
        return profile

    def seed_socials(self, profile):
        for i, s in enumerate(self.data["profile"].get("socials", [])):
            self._upsert(
                SocialLink, "social links", {"profile": profile, "label": s["label"]}, {"url": s["url"], "order": i}
            )

    def seed_skill_groups(self):
        for i, g in enumerate(self.data["skill_groups"]):
            self._upsert(
                SkillGroup, "skill groups", {"name": g["name"]}, {"skills": ", ".join(g["skills"]), "order": i}
            )

    def seed_experiences(self):
        for i, e in enumerate(self.data["experiences"]):
            self._upsert(
                Experience,
                "experiences",
                {"role": e["role"], "company": e["company"]},
                {
                    "location": e.get("location", ""),
                    "period": e["period"],
                    "is_current": e.get("is_current", False),
                    "summary": e.get("summary", ""),
                    "highlights": "\n".join(e.get("highlights", [])),
                    "technologies": ", ".join(e.get("technologies", [])),
                    "order": i,
                },
            )

    def seed_projects(self):
        for i, pr in enumerate(self.data["projects"]):
            self._upsert(
                Project,
                "projects",
                {"slug": pr["slug"]},
                {
                    "title": pr["title"],
                    "tagline": pr["tagline"],
                    "description": pr["description"],
                    "problem": pr.get("problem", ""),
                    "approach": pr.get("approach", ""),
                    "url": pr.get("url", ""),
                    "repo_url": pr.get("repo_url", ""),
                    "status": pr.get("status", Project.Status.PRODUCTION),
                    "stack": ", ".join(pr.get("stack", [])),
                    "featured": pr.get("featured", False),
                    "order": i,
                },
                files={"cover_image": pr.get("cover_image")},
            )

    def seed_labs(self):
        for i, lab in enumerate(self.data.get("labs", [])):
            self._upsert(
                Lab,
                "labs",
                {"title": lab["title"]},
                {
                    "category": lab["category"],
                    "provider": lab.get("provider", "AWS"),
                    "summary": lab["summary"],
                    "highlights": "\n".join(lab.get("highlights", [])),
                    "services": ", ".join(lab.get("services", [])),
                    "repo_url": lab.get("repo_url", ""),
                    "completed": lab.get("completed", ""),
                    "order": i,
                },
                files={"diagram": lab.get("diagram")},
            )

    def seed_education(self):
        for i, ed in enumerate(self.data["education"]):
            self._upsert(
                Education,
                "education",
                {"degree": ed["degree"]},
                {
                    "institution": ed["institution"],
                    "period": ed.get("period", ""),
                    "coursework": ed.get("coursework", ""),
                    "order": i,
                },
            )

    def seed_certifications(self):
        for i, c in enumerate(self.data["certifications"]):
            self._upsert(
                Certification,
                "certifications",
                {"name": c["name"]},
                {
                    "issuer": c.get("issuer", ""),
                    "year": c.get("year", ""),
                    "credential_url": c.get("credential_url", ""),
                    "order": i,
                },
                files={"image": c.get("image")},
            )

    def seed_contact_subjects(self):
        for i, label in enumerate(self.data.get("contact_subjects", [])):
            self._upsert(ContactSubject, "contact subjects", {"label": label}, {"is_active": True, "order": i})

    # ---------- Helpers ----------

    def _upsert(self, model, label, key, values, files=None):
        """Create the record if missing; overwrite it only in --update / --reset mode."""
        obj = model.objects.filter(**key).first()
        if obj is None:
            obj = model(**key, **values)
            for field, rel in (files or {}).items():
                self._attach(obj, field, rel)
            obj.save()
            self.stats[f"{label} created"] += 1
        elif self.update:
            for k, v in values.items():
                setattr(obj, k, v)
            for field, rel in (files or {}).items():
                self._attach(obj, field, rel, replace=True)
            obj.save()
            self.stats[f"{label} updated"] += 1
        else:
            for field, rel in (files or {}).items():
                self._restore_missing(obj, field, rel)
            self.stats[f"{label} kept"] += 1
        return obj

    def _attach(self, obj, field, rel_path, replace=False):
        """Copy a file from the seed media folder into the record's file field."""
        if not rel_path:
            return
        source = self.media_dir / rel_path
        if not source.exists():
            self.stderr.write(self.style.WARNING(f"Missing seed file, skipped: {source}"))
            return
        current = getattr(obj, field)
        if current and not replace:
            return
        if current and replace:
            current.delete(save=False)
        with source.open("rb") as fh:
            getattr(obj, field).save(source.name, File(fh), save=False)
        self.stats["files copied"] += 1

    def _restore_missing(self, obj, field, rel_path):
        """
        Put a seed file back when the record points at it but storage has lost it
        (e.g. a new server or an empty media volume). Only files that still carry the
        seed's own name are restored, so an image uploaded in the admin is never replaced.
        """
        current = getattr(obj, field)
        if not rel_path or not current or current.storage.exists(current.name):
            return
        source = self.media_dir / rel_path
        if not source.exists() or Path(current.name).name != source.name:
            return
        with source.open("rb") as fh:
            saved = current.storage.save(current.name, File(fh))
        if saved != current.name:  # storage picked another name; keep the record pointing at it
            setattr(obj, field, saved)
            obj.save(update_fields=[field])
        self.stats["files restored"] += 1

    def _delete_files(self, obj):
        for f in obj._meta.get_fields():
            if getattr(f, "upload_to", None) is not None:
                file = getattr(obj, f.name)
                if file:
                    file.delete(save=False)

    def report(self):
        if not self.stats:
            return
        width = max(len(k) for k in self.stats)
        for key in sorted(self.stats):
            self.stdout.write(f"  {key.ljust(width)}  {self.stats[key]}")
        self.stdout.write(self.style.SUCCESS("Portfolio content seeded."))
