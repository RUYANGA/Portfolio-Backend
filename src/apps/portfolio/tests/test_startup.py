"""Startup commands: wait_for_db, ensure_superuser."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class StartupCommandTests(TestCase):
    def test_wait_for_db_returns_when_database_is_up(self):
        out = StringIO()
        call_command("wait_for_db", "--timeout", "5", stdout=out)
        self.assertIn("Database ready", out.getvalue())

    def test_ensure_superuser_creates_once_and_never_resets_password(self):
        from unittest import mock

        from django.contrib.auth import get_user_model

        env = {
            "DJANGO_SUPERUSER_USERNAME": "owner",
            "DJANGO_SUPERUSER_PASSWORD": "first-pass-123",
            "DJANGO_SUPERUSER_EMAIL": "o@example.com",
        }
        with mock.patch.dict("os.environ", env):
            call_command("ensure_superuser", stdout=StringIO())
            user = get_user_model().objects.get(username="owner")
            self.assertTrue(user.is_superuser)
            user.set_password("changed-in-admin")
            user.save()

            call_command("ensure_superuser", stdout=StringIO())

        user.refresh_from_db()
        self.assertTrue(user.check_password("changed-in-admin"))
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_ensure_superuser_skips_without_settings(self):
        from unittest import mock

        from django.contrib.auth import get_user_model

        with mock.patch.dict("os.environ", {"DJANGO_SUPERUSER_USERNAME": "", "DJANGO_SUPERUSER_PASSWORD": ""}):
            call_command("ensure_superuser", stdout=StringIO())
        self.assertEqual(get_user_model().objects.count(), 0)
