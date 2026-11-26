"""The owner's notification email for contact-form messages."""

from unittest import mock

from django.core import mail
from django.test import override_settings

from apps.portfolio.models import ContactMessage, Profile

from .base import SeedTestCase, seed

BODY = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "subject": "Full-time job opportunity",
    "message": "Hello Merci,\nWe have a backend role <b>open</b> and would like to talk.",
}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CONTACT_NOTIFY_EMAIL="owner@example.com",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    SITE_URL="https://portfolio.example.com",
)
class ContactEmailTests(SeedTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()  # the contact endpoint allows 5 messages an hour per visitor
        seed()

    def send(self, **fields):
        res = self.client.post("/api/contact/", {**BODY, **fields}, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(len(mail.outbox), 1)
        return mail.outbox[0]

    def html(self, email):
        return email.alternatives[0][0]

    def test_headers_let_the_owner_reply_straight_to_the_visitor(self):
        email = self.send()
        owner = Profile.objects.get().name
        self.assertEqual(email.to, ["owner@example.com"])
        self.assertEqual(email.reply_to, ['"Ada Lovelace" <ada@example.com>'])
        self.assertEqual(email.from_email, f'"{owner} · Portfolio" <noreply@example.com>')
        self.assertIn('Reply-To: "Ada Lovelace" <ada@example.com>', email.message().as_string())
        self.assertEqual(email.subject, "New message from Ada Lovelace · Full-time job opportunity")

    def test_html_and_text_versions_carry_the_message(self):
        email = self.send()
        html = self.html(email)
        pk = ContactMessage.objects.get().pk
        self.assertEqual(email.alternatives[0][1], "text/html")
        self.assertIn("Hello Merci,<br>", html)
        self.assertIn("mailto:ada@example.com?subject=Re%3A%20Full-time%20job%20opportunity", html)
        self.assertIn("https://portfolio.example.com/admin/messages", html)
        self.assertIn(f"Message #{pk}", html)
        self.assertIn(">AL<", html)  # sender initials
        self.assertIn("We have a backend role <b>open</b>", email.body)
        self.assertIn("Open in dashboard: https://portfolio.example.com/admin/messages", email.body)

    def test_visitor_text_is_escaped_in_html(self):
        html = self.html(self.send(name="<script>x</script> Eve"))
        self.assertNotIn("<b>open</b>", html)
        self.assertIn("&lt;b&gt;open&lt;/b&gt;", html)
        self.assertNotIn("<script>x</script>", html)

    @override_settings(SITE_URL="")
    def test_dashboard_link_is_left_out_without_a_site_url(self):
        email = self.send()
        self.assertNotIn("/admin/messages", self.html(email))
        self.assertNotIn("Open in dashboard", email.body)

    @override_settings(DEFAULT_FROM_EMAIL="Merci <hello@example.com>")
    def test_a_named_from_address_is_kept(self):
        self.assertEqual(self.send().from_email, "Merci <hello@example.com>")

    def test_message_is_saved_even_when_sending_fails(self):
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            with self.assertLogs("apps.portfolio.api.public.views", "ERROR"):
                res = self.client.post("/api/contact/", BODY, content_type="application/json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(ContactMessage.objects.filter(email="ada@example.com").exists())
