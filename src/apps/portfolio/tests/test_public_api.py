"""Public API used by the site."""

from django.test import override_settings

from apps.portfolio.models import Profile

from .base import SEED_DATA, SeedTestCase, seed


class PortfolioApiTests(SeedTestCase):
    @override_settings(PUBLIC_URL="")
    def test_portfolio_endpoint_returns_absolute_media_urls(self):
        seed()
        data = self.client.get("/api/portfolio/").json()

        self.assertEqual(data["profile"]["name"], SEED_DATA["profile"]["name"])
        self.assertEqual(data["profile"]["contact_heading"], SEED_DATA["profile"]["contact_heading"])
        self.assertTrue(data["profile"]["cv_file"].startswith("http://"))
        self.assertTrue(all(c["image"].startswith("http://") for c in data["certifications"]))
        covers = [p["cover_image"] for p in data["projects"] if p["cover_image"]]
        self.assertTrue(covers and all(u.startswith("http://") for u in covers))


class DeploymentTests(SeedTestCase):
    def test_health_endpoint_checks_the_database(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})

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
