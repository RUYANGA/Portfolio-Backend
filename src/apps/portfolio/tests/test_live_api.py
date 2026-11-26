"""Live-panel endpoints: real data from the database, a random record per request."""

from apps.portfolio.models import Certification, Experience, Lab, Project, SkillGroup

from .base import SEED_DATA, SeedTestCase, seed


class LiveApiTests(SeedTestCase):
    def setUp(self):
        super().setUp()
        seed()

    def get(self, path):
        res = self.client.get(f"/api/{path}")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_random_project_comes_from_the_database(self):
        titles = set(Project.objects.values_list("title", flat=True))
        seen = {self.get("projects/random/")["title"] for _ in range(25)}
        self.assertTrue(seen <= titles)
        self.assertGreater(len(seen), 1)  # several different projects across requests
        self.assertLessEqual(len(self.get("projects/random/")["stack"]), 5)

    def test_project_detail_route_still_works(self):
        slug = SEED_DATA["projects"][0]["slug"]
        self.assertEqual(self.get(f"projects/{slug}/")["slug"], slug)

    def test_lab_skill_and_certification_endpoints(self):
        Lab.objects.all().delete()
        lab = Lab.objects.create(title="VPC lab", category="Networking", summary="s", services="VPC, NAT Gateway")
        self.assertEqual(self.get("labs/random/")["services"], ["VPC", "NAT Gateway"])
        lab.delete()
        self.assertIn(self.get("skills/random/")["group"], set(SkillGroup.objects.values_list("name", flat=True)))
        self.assertIn(
            self.get("certifications/random/")["name"], set(Certification.objects.values_list("name", flat=True))
        )

    def test_current_experience(self):
        current = Experience.objects.filter(is_current=True).first() or Experience.objects.first()
        assert current is not None
        data = self.get("experience/current/")
        self.assertEqual((data["role"], data["company"]), (current.role, current.company))

    def test_stats_reflect_the_database(self):
        data = self.get("stats/")
        self.assertEqual(data["projects"], Project.objects.count())
        self.assertEqual(data["certifications"], Certification.objects.count())
        self.assertEqual(data["skills"], sum(len(g.skill_list) for g in SkillGroup.objects.all()))
        self.assertIn("served_at", data)

    def test_empty_tables_answer_404(self):
        Lab.objects.all().delete()
        self.assertEqual(self.client.get("/api/labs/random/").status_code, 404)
