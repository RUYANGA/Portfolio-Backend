from django.db import models
from django.utils import timezone


class Hit(models.Model):
    """One page view, or one action (résumé download, booking, contact message)."""

    class Kind(models.TextChoices):
        VIEW = "view", "Page view"
        EVENT = "event", "Event"

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.VIEW)
    name = models.CharField(max_length=40, blank=True, help_text="Event name, e.g. cv_download.")
    target = models.CharField(max_length=120, blank=True, help_text="Event detail: section, link host…")
    path = models.CharField(max_length=200)
    referrer = models.CharField(max_length=120, blank=True, help_text="Host of the referring site.")
    source = models.CharField(max_length=60, blank=True, help_text="utm_source, when the link had one.")
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2 code.")
    region = models.CharField(max_length=64, blank=True)
    city = models.CharField(max_length=80, blank=True)
    device = models.CharField(max_length=10, blank=True)
    browser = models.CharField(max_length=20, blank=True)
    os = models.CharField(max_length=20, blank=True)
    language = models.CharField(max_length=8, blank=True)
    visitor = models.CharField(max_length=16, db_index=True, help_text="Daily-rotating anonymous hash.")
    session = models.CharField(max_length=32, blank=True, db_index=True)
    duration = models.PositiveIntegerField(default=0, help_text="Seconds spent on the page.")
    last_seen = models.DateTimeField(
        null=True, blank=True, db_index=True, help_text="Last heartbeat while the page was open (live visitors)."
    )
    scroll = models.PositiveSmallIntegerField(default=0, help_text="How far down the page they got, in %.")
    returning = models.BooleanField(default=False, help_text="This browser had visited before.")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["kind", "created_at"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.name or self.path} at {self.created_at:%Y-%m-%d %H:%M}"
