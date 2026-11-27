"""Dashboard CV builder: draft, preview, publish (the site's CV changes), versions and restore."""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.portfolio.models import Profile, Resume, ResumeVersion
from apps.portfolio.resume_content import first_draft

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class ResumeApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        get_user_model().objects.create_superuser("owner", "o@example.com", "owner-pass-123")
        res = self.client.post(
            "/api/admin/auth/login/",
            {"username": "owner", "password": "owner-pass-123"},
            content_type="application/json",
        )
        self.token = f"Token {res.json()['token']}"
        if not Profile.objects.exists():
            Profile.objects.create(
                name="Merci Ruyanga", title="Backend Engineer", headline="x", summary="y", email="m@x.co"
            )

    def api(self, method, path, data=None):
        return getattr(self.client, method)(
            f"/api/admin/resume/{path}", data, content_type="application/json", HTTP_AUTHORIZATION=self.token
        )

    def content(self, **changes):
        return {**first_draft(), **changes}

    def test_requires_staff(self):
        self.assertEqual(self.client.get("/api/admin/resume/").status_code, 401)

    def test_first_draft_is_the_current_cv(self):
        data = self.api("get", "").json()
        self.assertEqual(data["content"]["basics"]["name"], "Merci Ruyanga")
        self.assertTrue(data["content"]["competencies"])  # from seed/resume.json
        self.assertTrue(data["unpublished"])
        self.assertEqual(data["versions"], [])

    def test_save_draft_validates(self):
        res = self.api("put", "", {"content": self.content(summary="New summary")})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Resume.objects.get().content["summary"], "New summary")
        bad = self.api("put", "", {"content": self.content(basics={"name": ""})})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("name is required", bad.json()["detail"])
        too_long = self.api("put", "", {"content": self.content(summary="x" * 3000)})
        self.assertEqual(too_long.status_code, 400)

    def test_preview_returns_a_pdf(self):
        res = self.api("post", "preview/", {"content": self.content()})
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertTrue(res.content.startswith(b"%PDF"))

    def test_publish_makes_it_the_sites_cv_and_keeps_versions(self):
        first = self.api("post", "publish/", {"content": self.content(), "note": "First"})
        self.assertEqual(first.status_code, 201)
        profile = Profile.objects.get()
        self.assertEqual(profile.cv_file.name, "cv/v1/Merci_Ruyanga_CV.pdf")
        self.assertTrue(profile.cv_file.read().startswith(b"%PDF"))
        data = first.json()
        self.assertEqual(data["live"], {"source": "builder", "version": 1, "url": data["live"]["url"]})
        self.assertFalse(data["unpublished"])

        second = self.api("post", "publish/", {"content": self.content(summary="Updated")}).json()
        self.assertEqual([v["number"] for v in second["versions"]], [2, 1])
        self.assertEqual(Profile.objects.get().cv_file.name, "cv/v2/Merci_Ruyanga_CV.pdf")
        self.assertTrue(second["versions"][0]["live"])

        # The public API serves the new CV.
        public = self.client.get("/api/portfolio/").json()["profile"]["cv_file"]
        self.assertTrue(public.endswith("/cv/v2/Merci_Ruyanga_CV.pdf"))

    def test_restore_loads_a_version_into_the_draft(self):
        self.api("post", "publish/", {"content": self.content(summary="Version one")})
        self.api("post", "publish/", {"content": self.content(summary="Version two")})
        data = self.api("post", "versions/1/restore/").json()
        self.assertEqual(data["content"]["summary"], "Version one")
        self.assertTrue(data["unpublished"])
        self.assertEqual(ResumeVersion.objects.count(), 2)  # restoring doesn't publish
        self.assertEqual(self.api("post", "versions/99/restore/").status_code, 404)

    def test_uploaded_pdf_is_reported(self):
        profile = Profile.objects.get()
        profile.cv_file.name = "cv/Merci_Ruyanga_CV.pdf"
        profile.save()
        self.assertEqual(self.api("get", "").json()["live"]["source"], "upload")

    def test_import_from_portfolio(self):
        data = self.api("get", "import/").json()
        self.assertEqual(data["content"]["basics"]["name"], "Merci Ruyanga")
