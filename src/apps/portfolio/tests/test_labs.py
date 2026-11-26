"""Cloud labs: seeding, the public section and dashboard editing."""

import json
import os
import tempfile
from pathlib import Path

from django.test import override_settings

from apps.portfolio.models import Lab

from .base import SEED_DATA, SeedTestCase, seed

# Self-contained lab entries, so these tests don't depend on what the real seed file lists.
LABS = [
    {
        "title": "Multi-AZ network",
        "category": "Networking & security",
        "summary": "Private-by-default VPC.",
        "highlights": ["No inbound SSH", "NAT per AZ"],
        "services": ["Amazon VPC", "Application Load Balancer"],
        "repo_url": "https://github.com/example/network",
        "diagram": "projects/inuma.jpg",
        "completed": "Oct 2026",
    },
    {
        "title": "IAM onboarding",
        "category": "Identity & access",
        "summary": "Access managed as code.",
        "services": ["AWS IAM"],
    },
]


class LabSeedAndPublicApiTests(SeedTestCase):
    def setUp(self):
        super().setUp()
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.seed_file = Path(path)
        self.seed_file.write_text(json.dumps({**SEED_DATA, "labs": LABS}), encoding="utf-8")

    def tearDown(self):
        self.seed_file.unlink(missing_ok=True)
        super().tearDown()

    def seed_labs(self, *args):
        return seed("--file", str(self.seed_file), *args)

    def test_seed_loads_every_lab_in_order_with_diagrams(self):
        self.seed_labs()
        self.assertEqual(list(Lab.objects.values_list("title", flat=True)), [lab["title"] for lab in LABS])
        first, second = Lab.objects.all()
        self.assertTrue(first.diagram)
        self.assertFalse(second.diagram)
        self.assertEqual(first.provider, "AWS")
        self.assertEqual(first.services, "Amazon VPC, Application Load Balancer")

    def test_rerun_keeps_admin_edits(self):
        self.seed_labs()
        lab = Lab.objects.get(title="Multi-AZ network")
        lab.summary = "Edited in the dashboard"
        lab.save()
        self.seed_labs()
        self.assertEqual(Lab.objects.count(), len(LABS))
        self.assertEqual(Lab.objects.get(pk=lab.pk).summary, "Edited in the dashboard")

    @override_settings(PUBLIC_URL="")
    def test_portfolio_endpoint_lists_labs_with_split_fields(self):
        self.seed_labs()
        first, second = self.client.get("/api/portfolio/").json()["labs"]
        self.assertEqual(first["services"], LABS[0]["services"])
        self.assertEqual(first["highlights"], LABS[0]["highlights"])
        self.assertTrue(first["diagram"].startswith("http://"))
        self.assertIsNone(second["diagram"])
        self.assertEqual(second["highlights"], [])


class LabAdminApiTests(SeedTestCase):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model
        from django.core.cache import cache

        cache.clear()
        get_user_model().objects.create_superuser("owner", "o@example.com", "owner-pass-123")
        res = self.client.post(
            "/api/admin/auth/login/",
            {"username": "owner", "password": "owner-pass-123"},
            content_type="application/json",
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Token {res.json()['token']}"}

    def api(self, method, url, data=None):
        body = json.dumps(data) if data is not None else None
        return getattr(self.client, method)(f"/api/admin/{url}", body, content_type="application/json", **self.auth)

    def test_lab_crud_with_list_fields(self):
        res = self.api(
            "post",
            "labs/",
            {
                "title": "Serverless image pipeline",
                "category": "Serverless",
                "summary": "Resizes uploads with Lambda.",
                "services": ["AWS Lambda", "Amazon S3"],
                "highlights": ["Event-driven", "Pay per use"],
            },
        )
        self.assertEqual(res.status_code, 201, res.content)
        pk = res.json()["id"]
        lab = Lab.objects.get(pk=pk)
        self.assertEqual(lab.provider, "AWS")
        self.assertEqual(lab.services, "AWS Lambda, Amazon S3")
        self.assertEqual(lab.highlights, "Event-driven\nPay per use")

        res = self.api("patch", f"labs/{pk}/", {"services": ["AWS Lambda"]})
        self.assertEqual(res.json()["services"], ["AWS Lambda"])

        self.assertEqual(self.api("get", "overview/").json()["counts"]["labs"], 1)
        self.assertEqual(self.api("delete", f"labs/{pk}/").status_code, 204)

    def test_labs_require_a_staff_token(self):
        self.assertEqual(self.client.get("/api/admin/labs/").status_code, 401)
