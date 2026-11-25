"""Dashboard API: auth, CRUD, uploads, reorder, inbox."""

import json
from pathlib import Path

from apps.portfolio.models import ContactMessage, Experience, Profile, Project, SkillGroup, SocialLink

from .base import SeedTestCase, seed


class AdminApiTests(SeedTestCase):
    """The staff-only API used by the Next.js dashboard."""

    def setUp(self):
        super().setUp()
        seed()
        from django.contrib.auth import get_user_model
        from django.core.cache import cache

        cache.clear()  # reset login throttling between tests
        User = get_user_model()
        User.objects.create_superuser("owner", "o@example.com", "owner-pass-123")
        User.objects.create_user("visitor", "v@example.com", "visitor-pass-123")
        res = self.client.post(
            "/api/admin/auth/login/",
            {"username": "owner", "password": "owner-pass-123"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.auth = {"HTTP_AUTHORIZATION": f"Token {res.json()['token']}"}

    def api(self, method, url, data=None, multipart=False, **kwargs):
        from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

        if data is not None and multipart:
            data, kwargs["content_type"] = encode_multipart(BOUNDARY, data), MULTIPART_CONTENT
        elif data is not None:
            data, kwargs["content_type"] = json.dumps(data), "application/json"
        return getattr(self.client, method)(f"/api/admin/{url}", data, **self.auth, **kwargs)

    def test_requires_a_staff_token(self):
        self.assertEqual(self.client.get("/api/admin/projects/").status_code, 401)
        res = self.client.post(
            "/api/admin/auth/login/",
            {"username": "visitor", "password": "visitor-pass-123"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)
        res = self.client.post(
            "/api/admin/auth/login/", {"username": "owner", "password": "wrong"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 400)

    def test_expired_token_is_rejected(self):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.authtoken.models import Token

        Token.objects.update(created=timezone.now() - timedelta(days=30))
        self.assertEqual(self.api("get", "auth/me/").status_code, 401)

    def test_logout_revokes_the_token(self):
        self.assertEqual(self.api("post", "auth/logout/").status_code, 204)
        self.assertEqual(self.api("get", "auth/me/").status_code, 401)

    def test_project_crud_with_list_fields(self):
        res = self.api(
            "post",
            "projects/",
            {
                "title": "New system",
                "slug": "new-system",
                "tagline": "t",
                "description": "d",
                "stack": ["Django", "PostgreSQL"],
                "status": "in_progress",
            },
        )
        self.assertEqual(res.status_code, 201, res.content)
        pk = res.json()["id"]
        self.assertEqual(Project.objects.get(pk=pk).stack, "Django, PostgreSQL")
        self.assertEqual(res.json()["stack"], ["Django", "PostgreSQL"])
        self.assertEqual(Project.objects.get(pk=pk).order, Project.objects.latest("order").order)

        res = self.api("patch", f"projects/{pk}/", {"featured": True, "stack": ["Django"]})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Project.objects.get(pk=pk).featured)

        self.assertEqual(self.api("delete", f"projects/{pk}/").status_code, 204)
        self.assertFalse(Project.objects.filter(pk=pk).exists())

    def test_image_upload_and_removal(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image as PILImage

        buf = __import__("io").BytesIO()
        PILImage.new("RGB", (8, 8), "teal").save(buf, "PNG")
        project = Project.objects.get(slug="inuma")
        old_path = Path(project.cover_image.path)

        upload = SimpleUploadedFile("new-cover.png", buf.getvalue(), content_type="image/png")
        res = self.api(
            "patch",
            f"projects/{project.pk}/",
            {"cover_image": upload, "stack": json.dumps(["Node.js"])},
            multipart=True,
        )
        self.assertEqual(res.status_code, 200, res.content)
        project.refresh_from_db()
        self.assertIn("new-cover", project.cover_image.name)
        self.assertFalse(old_path.exists(), "replaced file should be deleted")
        self.assertEqual(project.stack, "Node.js")

        res = self.api("patch", f"projects/{project.pk}/", {"cover_image": ""}, multipart=True)
        self.assertEqual(res.status_code, 200, res.content)
        project.refresh_from_db()
        self.assertFalse(project.cover_image)

    def test_reorder(self):
        ids = list(SkillGroup.objects.values_list("id", flat=True))[::-1]
        res = self.api("post", "skill-groups/reorder/", {"ids": ids})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(list(SkillGroup.objects.values_list("id", flat=True)), ids)

    def test_profile_and_social_links(self):
        res = self.api("patch", "profile/", {"contact_heading": "Say hello", "years_experience": 5})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Profile.objects.get().contact_heading, "Say hello")
        res = self.api("post", "social-links/", {"label": "X", "url": "https://x.com/someone"})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(SocialLink.objects.get(label="X").profile, Profile.objects.get())

    def test_experience_highlights_are_lines(self):
        exp = Experience.objects.earliest("order")
        res = self.api("patch", f"experiences/{exp.pk}/", {"highlights": ["First", "Second"]})
        self.assertEqual(res.status_code, 200)
        exp.refresh_from_db()
        self.assertEqual(exp.highlights, "First\nSecond")

    def test_messages_inbox(self):
        msg = ContactMessage.objects.create(name="A", email="a@example.com", message="Hello there, a message.")
        self.assertEqual(self.api("get", "overview/").json()["counts"]["unread_messages"], 1)
        self.assertEqual(self.api("patch", f"messages/{msg.pk}/", {"is_read": True}).status_code, 200)
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)
        self.assertEqual(self.api("post", "messages/", {"name": "x"}).status_code, 405)
