"""The résumé PDF renderer: the CV's format, links, hidden sections and odd input."""

import re
from typing import Any

from django.test import SimpleTestCase

from apps.portfolio.resume_pdf import render

CONTENT: dict[str, Any] = {
    "basics": {
        "name": "Ada Lovelace",
        "title": "Backend Engineer | Full-Stack Developer",
        "location": "London, UK",
        "phone": "+44 20 0000 0000",
        "email": "ada@example.com",
        "website": "https://ada.dev",
        "github": "https://github.com/ada",
        "linkedin": "https://linkedin.com/in/ada",
    },
    "summary": "Engineer who builds reliable systems.",
    "competencies": ["API design", "Event-driven systems"],
    "skills": [{"group": "Backend", "items": "Python, Django"}],
    "experience": [
        {
            "role": "Backend Engineer",
            "company": "Analytical Engines",
            "location": "London",
            "period": "2023 – Present",
            "bullets": ["Built the difference engine API."],
        }
    ],
    "projects": [
        {
            "name": "Notes",
            "subtitle": "Algorithm notes",
            "link": "https://notes.example.com",
            "bullets": ["First published program."],
            "tech": "Python",
        }
    ],
    "education": [{"degree": "BSc Mathematics", "school": "Home study", "period": "", "coursework": "Calculus"}],
    "certifications": [{"name": "AWS Certified Cloud Practitioner", "issuer": "", "year": "2026"}],
    "extra": [{"title": "Engineering approach", "bullets": ["Secure by default."]}],
    "order": ["summary", "competencies", "skills", "experience", "projects", "education", "certifications", "extra"],
    "hidden": [],
    "titles": {},
}


class ResumePdfTests(SimpleTestCase):
    def test_renders_a_pdf_in_the_cv_format(self):
        pdf = render(CONTENT)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"Carlito", pdf)  # the CV's font is embedded
        self.assertIn(b"https://github.com/ada", pdf)  # clickable links
        self.assertIn(b"mailto:ada@example.com", pdf)
        self.assertIn(b"Ada Lovelace", pdf)  # document title / author metadata

    def test_short_content_fits_one_page(self):
        self.assertEqual(len(re.findall(rb"/Type /Page\b", render(CONTENT))), 1)

    def test_hidden_sections_are_left_out(self):
        hidden = render({**CONTENT, "hidden": ["projects", "extra"]})
        self.assertNotIn(b"https://notes.example.com", hidden)
        self.assertIn(b"https://notes.example.com", render(CONTENT))

    def test_special_characters_are_safe(self):
        content = {**CONTENT, "summary": "Uses <b>tags</b> & ampersands > signs", "competencies": ["a < b"]}
        self.assertTrue(render(content).startswith(b"%PDF"))

    def test_minimal_and_long_content(self):
        self.assertTrue(render({"basics": {"name": "Only A Name"}}).startswith(b"%PDF"))
        long = {**CONTENT, "experience": CONTENT["experience"] * 12}
        self.assertGreater(len(re.findall(rb"/Type /Page\b", render(long))), 1)  # flows onto more pages
