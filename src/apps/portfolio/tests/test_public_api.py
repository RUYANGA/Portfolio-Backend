"""Public API used by the site."""

import os
from unittest import mock

from django.test import override_settings

from apps.portfolio.models import ContactMessage, ContactSubject, Profile

from .base import SEED_DATA, SeedTestCase, seed


class PortfolioApiTests(SeedTestCase):
    @override_settings(PUBLIC_URL="")
    def test_portfolio_endpoint_returns_absolute_media_urls(self):
        seed()
        data = self.client.get("/api/portfolio/").json()

        self.assertEqual(data["profile"]["name"], SEED_DATA["profile"]["name"])
        self.assertEqual(data["profile"]["contact_heading"], SEED_DATA["profile"]["contact_heading"])
        self.assertEqual(data["profile"]["secondary_email"], SEED_DATA["profile"]["secondary_email"])
        self.assertTrue(data["profile"]["cv_file"].startswith("http://"))
        self.assertTrue(all(c["image"].startswith("http://") for c in data["certifications"]))
        covers = [p["cover_image"] for p in data["projects"] if p["cover_image"]]
        self.assertTrue(covers and all(u.startswith("http://") for u in covers))


class DeploymentTests(SeedTestCase):
    def test_health_endpoint_checks_the_database(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_health_endpoint_reports_the_running_version(self):
        with mock.patch.dict(os.environ, {"APP_VERSION": "307c316abcdef0123456"}):
            self.assertEqual(self.client.get("/api/health/").json()["version"], "307c316abcde")

    def test_media_links_use_public_url_when_set(self):
        seed()
        with override_settings(PUBLIC_URL="https://api.example.com", ALLOWED_HOSTS=["api", "testserver"]):
            data = self.client.get("/api/portfolio/", HTTP_HOST="api").json()
        self.assertTrue(data["profile"]["cv_file"].startswith("https://api.example.com/media/"))
        self.assertTrue(all(c["image"].startswith("https://api.example.com/media/") for c in data["certifications"]))


class MediaFramingTests(SeedTestCase):
    def test_uploads_can_be_framed_but_api_cannot(self):
        seed()
        cv = Profile.objects.get().cv_file
        with override_settings(MEDIA_ROOT=self.media):
            media = self.client.get(cv.url)
        self.assertEqual(media.status_code, 200)
        self.assertNotIn("X-Frame-Options", media.headers)
        self.assertEqual(self.client.get("/api/portfolio/").headers.get("X-Frame-Options"), "DENY")


class ContactSubjectTests(SeedTestCase):
    def setUp(self):
        super().setUp()
        seed()

    def post(self, **fields):
        body = {"name": "Ada", "email": "ada@example.com", "message": "I would like to talk about a backend role."}
        body.update(fields)
        return self.client.post("/api/contact/", body, content_type="application/json")

    def test_seed_loads_the_subjects_and_the_site_receives_them(self):
        subjects = self.client.get("/api/portfolio/").json()["contact_subjects"]
        self.assertEqual(subjects, SEED_DATA["contact_subjects"])

    def test_inactive_subjects_are_not_offered(self):
        ContactSubject.objects.filter(label="Other").update(is_active=False)
        self.assertNotIn("Other", self.client.get("/api/portfolio/").json()["contact_subjects"])

    def test_a_listed_subject_is_accepted(self):
        res = self.post(subject="Full-time job opportunity")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(ContactMessage.objects.get().subject, "Full-time job opportunity")

    def test_a_typed_or_missing_subject_is_rejected(self):
        self.assertEqual(self.post(subject="anything I like").status_code, 400)
        self.assertIn("subject", self.post(subject="").json())

    def test_any_subject_is_accepted_when_none_are_set_up(self):
        ContactSubject.objects.all().delete()
        self.assertEqual(self.post(subject="Hello").status_code, 201)
