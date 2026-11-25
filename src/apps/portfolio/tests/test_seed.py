"""Seeding: loading, re-runs, --update / --reset, file recovery."""

from pathlib import Path

from apps.portfolio.models import (
    Certification,
    ContactMessage,
    Education,
    Experience,
    Profile,
    Project,
    SkillGroup,
    SocialLink,
)

from .base import SEED_DATA, SeedTestCase, seed


class SeedCommandTests(SeedTestCase):
    def test_loads_everything_in_the_seed_file(self):
        seed()
        self.assertEqual(Profile.objects.count(), 1)
        self.assertEqual(SocialLink.objects.count(), len(SEED_DATA["profile"]["socials"]))
        self.assertEqual(SkillGroup.objects.count(), len(SEED_DATA["skill_groups"]))
        self.assertEqual(Experience.objects.count(), len(SEED_DATA["experiences"]))
        self.assertEqual(Project.objects.count(), len(SEED_DATA["projects"]))
        self.assertEqual(Education.objects.count(), len(SEED_DATA["education"]))
        self.assertEqual(Certification.objects.count(), len(SEED_DATA["certifications"]))

    def test_attaches_images_and_cv(self):
        seed()
        profile = Profile.objects.get()
        self.assertTrue(profile.cv_file)
        self.assertTrue(Path(profile.cv_file.path).exists())
        with_cover = [p["slug"] for p in SEED_DATA["projects"] if p.get("cover_image")]
        for slug in with_cover:
            self.assertTrue(Project.objects.get(slug=slug).cover_image, slug)
        for cert in Certification.objects.all():
            self.assertTrue(cert.image, cert.name)

    def test_rerun_creates_no_duplicates_and_keeps_admin_edits(self):
        seed()
        Project.objects.filter(slug="inuma").update(tagline="Edited in the admin")
        Profile.objects.update(contact_heading="My own heading")

        seed()

        self.assertEqual(Project.objects.count(), len(SEED_DATA["projects"]))
        self.assertEqual(Project.objects.get(slug="inuma").tagline, "Edited in the admin")
        self.assertEqual(Profile.objects.get().contact_heading, "My own heading")

    def test_update_overwrites_with_seed_values(self):
        seed()
        Project.objects.filter(slug="inuma").update(tagline="Edited in the admin")

        seed("--update")

        expected = next(p for p in SEED_DATA["projects"] if p["slug"] == "inuma")["tagline"]
        self.assertEqual(Project.objects.get(slug="inuma").tagline, expected)
        self.assertEqual(Project.objects.count(), len(SEED_DATA["projects"]))

    def test_reset_removes_extra_content_but_keeps_messages(self):
        seed()
        Project.objects.create(title="Temporary", slug="temporary", tagline="x", description="x")
        ContactMessage.objects.create(name="A", email="a@example.com", message="Hello there, a message.")

        seed("--reset")

        self.assertFalse(Project.objects.filter(slug="temporary").exists())
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_new_seed_entries_are_added_on_rerun(self):
        seed()
        Certification.objects.filter(name=SEED_DATA["certifications"][0]["name"]).delete()

        seed()

        self.assertEqual(Certification.objects.count(), len(SEED_DATA["certifications"]))


class SeedFileRecoveryTests(SeedTestCase):
    def test_lost_seed_files_are_restored_without_touching_records(self):
        seed()
        project = Project.objects.get(slug="inuma")
        Path(project.cover_image.path).unlink()

        seed()

        project.refresh_from_db()
        self.assertTrue(Path(project.cover_image.path).exists())

    def test_admin_uploaded_files_are_never_replaced(self):
        from django.core.files.base import ContentFile

        seed()
        project = Project.objects.get(slug="inuma")
        project.cover_image.save("my-own-screenshot.jpg", ContentFile(b"custom"), save=True)
        Path(project.cover_image.path).unlink()

        seed()

        project.refresh_from_db()
        self.assertEqual(Path(project.cover_image.name).name, "my-own-screenshot.jpg")
        self.assertFalse(Path(project.cover_image.path).exists())
