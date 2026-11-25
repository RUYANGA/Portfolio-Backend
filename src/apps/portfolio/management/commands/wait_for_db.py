"""Block until the database accepts connections, so startup doesn't race a database that is still booting."""

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Wait until the default database accepts connections."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait before giving up (default 60).")
        parser.add_argument("--interval", type=float, default=1.0, help="Seconds between attempts (default 1).")

    def handle(self, *args, timeout, interval, **options):
        connection = connections["default"]
        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                connection.ensure_connection()
                break
            except OperationalError as exc:
                if time.monotonic() >= deadline:
                    raise CommandError(f"Database not reachable after {timeout}s: {exc}") from exc
                if attempt == 1:
                    self.stdout.write("Waiting for the database…")
                connection.close()
                time.sleep(interval)
        self.stdout.write(self.style.SUCCESS(f"Database ready ({connection.vendor})."))
