"""Visitor analytics: collecting views/events from the site's server, and the dashboard report."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.analytics.models import Hit
from apps.analytics.views import parse_user_agent

KEY = "test-analytics-key"
AN_HOUR = timedelta(hours=1)
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


@override_settings(ANALYTICS_KEY=KEY, SITE_URL="https://www.ruyanga.com")
class CollectTests(TestCase):
    def collect(self, key=KEY, **data):
        body = {"type": "view", "path": "/", "ua": CHROME, "ip": "203.0.113.5", "session": "s1", **data}
        return self.client.post(
            "/api/analytics/collect/", json.dumps(body), content_type="application/json", HTTP_X_ANALYTICS_KEY=key
        )

    def test_view_is_stored_without_the_ip(self):
        res = self.collect(country="rw", city="Kigali", referrer="https://www.linkedin.com/feed/", language="en-US")
        self.assertEqual(res.status_code, 201)
        hit = Hit.objects.get(id=res.json()["id"])
        self.assertEqual((hit.country, hit.city, hit.referrer, hit.language), ("RW", "Kigali", "linkedin.com", "en"))
        self.assertEqual((hit.device, hit.browser, hit.os), ("Desktop", "Chrome", "Windows"))
        self.assertEqual(len(hit.visitor), 16)
        self.assertNotIn("203.0.113.5", str(Hit.objects.values().first()))

    def test_key_is_required(self):
        self.assertEqual(self.collect(key="wrong").status_code, 403)
        with override_settings(ANALYTICS_KEY="", DEBUG=False):
            self.assertEqual(self.collect(key="").status_code, 503)
        self.assertFalse(Hit.objects.exists())

    def test_bots_and_own_site_referrers_are_ignored(self):
        self.assertEqual(self.collect(ua="Googlebot/2.1 (+http://www.google.com/bot.html)").status_code, 204)
        self.assertFalse(Hit.objects.exists())
        self.collect(referrer="https://ruyanga.com/projects")
        self.assertEqual(Hit.objects.get().referrer, "")

    def test_private_tokens_are_stripped_from_paths(self):
        self.collect(path="/book/manage/secret-token-123?x=1")
        self.assertEqual(Hit.objects.get().path, "/book/manage")

    def test_time_on_page_is_recorded_and_capped(self):
        hit_id = self.collect().json()["id"]
        self.collect(type="leave", id=hit_id, seconds=42)
        self.assertEqual(Hit.objects.get().duration, 42)
        self.collect(type="leave", id=hit_id, seconds=99999)
        self.assertEqual(Hit.objects.get().duration, 1800)
        self.collect(type="leave", id=hit_id, seconds=5, session="someone-else")
        self.assertEqual(Hit.objects.get().duration, 1800)

    def test_events(self):
        self.assertEqual(self.collect(type="event", name="cv_download").status_code, 201)
        self.assertEqual(self.collect(type="event", name="anything").status_code, 400)
        self.assertEqual(Hit.objects.get().kind, Hit.Kind.EVENT)

    def test_user_agent_parsing(self):
        self.assertEqual(parse_user_agent(IPHONE), ("Mobile", "Safari", "iOS"))


class ReportTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner", "o@example.com", "owner-pass-123")
        res = self.client.post(
            "/api/admin/auth/login/",
            {"username": "owner", "password": "owner-pass-123"},
            content_type="application/json",
        )
        self.token = f"Token {res.json()['token']}"

    def hit(self, ago=AN_HOUR, **fields):
        defaults = {"path": "/", "visitor": "v1", "session": "s1", "country": "RW", "device": "Desktop"}
        return Hit.objects.create(created_at=timezone.now() - ago, **{**defaults, **fields})

    def report(self, query="?days=7&tz=Africa/Kigali"):
        return self.client.get(f"/api/admin/analytics/{query}", HTTP_AUTHORIZATION=self.token)

    def test_requires_staff(self):
        self.assertEqual(self.client.get("/api/admin/analytics/").status_code, 401)

    def test_totals_breakdowns_and_previous_period(self):
        self.hit(duration=30)
        self.hit(path="/book", duration=90)
        self.hit(visitor="v2", session="s2", country="US", city="Austin", referrer="google.com")
        self.hit(kind=Hit.Kind.EVENT, name="cv_download")
        self.hit(ago=timedelta(days=10), visitor="old", session="old")  # previous 7-day period

        data = self.report().json()
        self.assertEqual(data["totals"]["views"], 3)
        self.assertEqual(data["totals"]["visitors"], 2)
        self.assertEqual(data["totals"]["sessions"], 2)
        self.assertEqual(data["totals"]["bounce_rate"], 50.0)
        self.assertEqual(data["totals"]["avg_time"], 60)
        self.assertEqual(data["previous"]["views"], 1)
        self.assertEqual(data["countries"][0]["country"], "RW")
        self.assertEqual(data["cities"], [{"city": "Austin", "country": "US", "views": 1, "visitors": 1}])
        self.assertEqual({s["source"] for s in data["sources"]}, {"Direct", "google.com"})
        self.assertEqual(data["events"], [{"name": "cv_download", "count": 1, "visitors": 1}])
        self.assertEqual(len(data["series"]), 7)
        self.assertEqual(sum(d["views"] for d in data["series"]), 3)
        self.assertEqual(sum(data["hours"]), 3)
        self.assertEqual(data["live"]["visitors"], 0)
        self.assertNotIn("visitor", data["recent"][0])

    def test_live_visitors_and_hourly_today(self):
        self.hit(ago=timedelta(minutes=1), path="/projects")
        data = self.report("?days=1&tz=Bad/Zone").json()
        self.assertEqual(data["live"]["visitors"], 1)
        self.assertEqual(data["live"]["pages"][0]["path"], "/projects")
        self.assertNotIn("session", data["live"]["pages"][0])
        self.assertEqual(len(data["series"]), 24)
