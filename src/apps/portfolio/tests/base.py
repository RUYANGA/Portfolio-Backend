"""Shared test helpers: seed data, the seed() shortcut, and an isolated media folder."""

import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

SEED_FILE = Path(settings.SEED_DIR) / "portfolio.json"
SEED_DATA = json.loads(SEED_FILE.read_text(encoding="utf-8"))


def seed(*args):
    out = StringIO()
    call_command("seed_portfolio", *args, "--noinput", stdout=out, stderr=StringIO())
    return out.getvalue()


class SeedTestCase(TestCase):
    """Seeds into a throwaway MEDIA_ROOT so tests never touch real uploads."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
