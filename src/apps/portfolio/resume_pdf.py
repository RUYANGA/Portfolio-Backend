"""
Renders résumé content to a PDF in the owner's CV format: A4, Carlito, a centred navy name, blue
underlined contact links, navy section headings with a rule, and bullet lists.

The measurements below reproduce the original CV exactly, so a CV edited in the dashboard looks
the same as the one it replaces.

content = {
    "basics": {name, title, location, phone, email, website, github, linkedin},
    "summary": "…",
    "competencies": ["…"],
    "skills": [{group, items}],
    "experience": [{role, company, location, period, bullets: ["…"]}],
    "projects": [{name, subtitle, link, bullets: ["…"], tech}],
    "education": [{degree, school, period, coursework}],
    "certifications": [{name, issuer, year}],
    "extra": [{title, bullets: ["…"]}],     # sections of your own, e.g. "Engineering approach"
    "order": [section keys, top to bottom], "hidden": [keys], "titles": {key: heading},
}
"""

from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

SECTIONS = ["summary", "competencies", "skills", "experience", "projects", "education", "certifications", "extra"]
TITLES = {
    "summary": "Professional summary",
    "competencies": "Core competencies",
    "skills": "Technical skills",
    "experience": "Professional experience",
    "projects": "Key projects",
    "education": "Education",
    "certifications": "Certifications",
}

NAVY = "#1f2a44"
GREY = "#555555"
LINK = "#0563c1"
# Page margins; the frame adds 6pt of padding, so text starts 46pt from the sides and 32pt from the top.
SIDE_MARGIN = 40
TOP_MARGIN = 26
BOTTOM_MARGIN = 26

FONT_DIR = Path(__file__).resolve().parent / "fonts"
REGULAR, BOLD, ITALIC = "Carlito", "Carlito-Bold", "Carlito-Italic"


def _register_fonts() -> None:
    if REGULAR in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(REGULAR, FONT_DIR / "Carlito-Regular.ttf"))
    pdfmetrics.registerFont(TTFont(BOLD, FONT_DIR / "Carlito-Bold.ttf"))
    pdfmetrics.registerFont(TTFont(ITALIC, FONT_DIR / "Carlito-Italic.ttf"))
    pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD, italic=ITALIC, boldItalic=BOLD)


def _style(name: str, **kwargs: Any) -> ParagraphStyle:
    return ParagraphStyle(
        name, **{"fontName": REGULAR, "fontSize": 11, "leading": 14, "textColor": colors.black, **kwargs}
    )


class S:
    """Paragraph styles, measured from the original CV."""

    name = _style("name", fontName=BOLD, fontSize=20, leading=24, textColor=colors.HexColor(NAVY), alignment=TA_CENTER)
    title = _style("title", fontSize=12, leading=16, textColor=colors.HexColor(GREY), alignment=TA_CENTER)
    contact = _style("contact", fontSize=10, leading=13, alignment=TA_CENTER)
    heading = _style("heading", fontName=BOLD, fontSize=12, leading=14, textColor=colors.HexColor(NAVY), spaceBefore=6)
    body = _style("body", alignment=TA_JUSTIFY)
    line = _style("line")
    entry = _style("entry", spaceBefore=4)  # a job / project / degree line, 4pt below the previous entry
    bullet = _style(
        "bullet", leading=13.2, leftIndent=14, bulletIndent=4, bulletFontName="Helvetica", bulletFontSize=10
    )
    stack = _style("stack", fontName=ITALIC, leftIndent=14, textColor=colors.HexColor(GREY))


def _t(value: str) -> str:
    return escape(value or "")


def _shown(url: str) -> str:
    """How a link is printed: without the scheme, "www." or a trailing slash."""
    for prefix in ("https://", "http://", "mailto:", "tel:"):
        url = url.removeprefix(prefix)
    return url.removeprefix("www.").rstrip("/")


def _link(url: str, label: str | None = None) -> str:
    href = url if url.startswith(("http://", "https://", "mailto:", "tel:")) else f"https://{url}"
    text = _t(label or _shown(url))
    return f'<a href="{escape(href, {chr(34): "&quot;"})}" color="{LINK}"><u>{text}</u></a>'


def _heading(key: str, content: dict[str, Any]) -> list:
    title = (content.get("titles") or {}).get(key) or TITLES.get(key, key)
    return [
        Paragraph(_t(title.upper()), S.heading),
        HRFlowable(
            width="100%", thickness=1.2, color=colors.HexColor(NAVY), spaceBefore=2.6, spaceAfter=4.4, lineCap="round"
        ),
    ]


def _bullets(items: list[str]) -> list:
    return [Paragraph(_t(item), S.bullet, bulletText="•") for item in items if item]


def _entry(markup: str, first: bool) -> Paragraph:
    return Paragraph(markup, S.line if first else S.entry)


def _summary(content: dict[str, Any]) -> list[list]:
    return [[Paragraph(_t(content.get("summary", "")), S.body)]] if content.get("summary") else []


def _competencies(content: dict[str, Any]) -> list[list]:
    return [[b] for b in _bullets(content.get("competencies") or [])]


def _skills(content: dict[str, Any]) -> list[list]:
    return [
        [Paragraph(f"<b>{_t(s['group'])}:</b> {_t(s['items'])}", S.line)]
        for s in content.get("skills") or []
        if s.get("group") or s.get("items")
    ]


def _certifications(content: dict[str, Any]) -> list[list]:
    rows = [
        c["name"] + (f", {c['issuer']}" if c.get("issuer") else "") + (f" ({c['year']})" if c.get("year") else "")
        for c in content.get("certifications") or []
    ]
    return [[b] for b in _bullets(rows)]


def _period(item: dict[str, Any]) -> str:
    return f' <font size="10" color="{GREY}">{_t(item["period"])}</font>' if item.get("period") else ""


def _experience(content: dict[str, Any]) -> list[list]:
    """ "Role | Company, Location  period" followed by bullets."""
    blocks = []
    for i, item in enumerate(content.get("experience") or []):
        place = ", ".join(p for p in (item.get("company"), item.get("location")) if p)
        line = f"<b>{_t(item['role'])}</b>" + (f" | <i>{_t(place)}</i>" if place else "") + _period(item)
        blocks.append([_entry(line, i == 0)] + _bullets(item.get("bullets") or []))
    return blocks


def _projects(content: dict[str, Any]) -> list[list]:
    """ "Name — Subtitle (link)", bullets, then a grey "Stack:" line."""
    blocks = []
    for i, item in enumerate(content.get("projects") or []):
        name = item["name"] + (f" — {item['subtitle']}" if item.get("subtitle") else "")
        line = f"<b>{_t(name)}</b>" + (f" ({_link(item['link'])})" if item.get("link") else "")
        block = [_entry(line, i == 0)] + _bullets(item.get("bullets") or [])
        if item.get("tech"):
            block.append(Paragraph(f"Stack: {_t(item['tech'])}", S.stack))
        blocks.append(block)
    return blocks


def _education(content: dict[str, Any]) -> list[list]:
    blocks = []
    for i, item in enumerate(content.get("education") or []):
        block = [_entry(f"<b>{_t(item['degree'])}</b>" + _period(item), i == 0)]
        if item.get("school"):
            block.append(Paragraph(_t(item["school"]), S.line))
        if item.get("coursework"):
            block.append(Paragraph(f"<i>Relevant Coursework:</i> {_t(item['coursework'])}", S.body))
        blocks.append(block)
    return blocks


# Each section's content as blocks; a block is never split across pages.
BLOCKS = {
    "summary": _summary,
    "competencies": _competencies,
    "skills": _skills,
    "experience": _experience,
    "projects": _projects,
    "education": _education,
    "certifications": _certifications,
}


def _section(key: str, content: dict[str, Any]) -> list:
    if key == "extra":
        flow: list = []
        for section in content.get("extra") or []:
            bullets = _bullets(section.get("bullets") or [])
            if section.get("title") and bullets:
                title = {"titles": {"extra": section["title"]}}
                flow += [KeepTogether(_heading("extra", title) + bullets[:1])] + bullets[1:]
        return flow
    blocks = BLOCKS[key](content)
    if not blocks:
        return []
    # The heading stays with the first block, and no entry is split across pages.
    return [KeepTogether(_heading(key, content) + blocks[0])] + [KeepTogether(b) for b in blocks[1:]]


def _contact(basics: dict[str, str]) -> list[str]:
    """The three centred contact lines of the original CV."""
    sep = " • "
    first = [_t(basics[k]) for k in ("location", "phone") if basics.get(k)]
    if basics.get("email"):
        first.append(_link(f"mailto:{basics['email']}", basics["email"]))
    second = []
    if basics.get("website"):
        second.append(f"Portfolio: {_link(basics['website'])}")
    if basics.get("github"):
        second.append(f"GitHub: {_link(basics['github'])}")
    third = [f"LinkedIn: {_link(basics['linkedin'])}"] if basics.get("linkedin") else []
    return [sep.join(line) for line in (first, second, third) if line]


def render(content: dict[str, Any]) -> bytes:
    """The résumé as PDF bytes."""
    _register_fonts()
    basics = content.get("basics") or {}
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=SIDE_MARGIN,
        rightMargin=SIDE_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"{basics.get('name', '')} – CV",
        author=basics.get("name", ""),
        subject=basics.get("title", ""),
    )
    story: list = [Paragraph(_t(basics.get("name", "").upper()), S.name)]
    if basics.get("title"):
        story.append(Paragraph(_t(basics["title"]), S.title))
    story += [Paragraph(line, S.contact) for line in _contact(basics)]
    story.append(Spacer(1, 4))

    hidden = set(content.get("hidden") or [])
    order = [k for k in content.get("order") or SECTIONS if k in SECTIONS]
    order += [k for k in SECTIONS if k not in order]
    for key in order:
        if key not in hidden:
            story += _section(key, content)

    doc.build(story)
    return buffer.getvalue()
