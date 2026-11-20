"""Draft text -> PDF attachment.

Professional human format by default (config/settings.yaml -> cv_style):
  Times New Roman (PDF standard Times), size 12, comfortable leading,
  bold uppercase section headings and bold subheadings, generous paragraph
  spacing, and clean round dot bullets, never machine-looking markers.
"""
import os
import re

import yaml
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONTS = {
    "times": {"body": "Times-Roman", "bold": "Times-Bold", "italic": "Times-Italic"},
    "helvetica": {"body": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique"},
}
HEADING_COLORS = {"black": colors.HexColor("#000000"), "navy": colors.HexColor("#1a355e")}


def _cfg() -> dict:
    try:
        from agent.config import load_settings
        s = load_settings()
        return s.get("cv_style") or {}
    except Exception:
        return {}


def _styles():
    c = _cfg()
    fam = FONTS.get((c.get("font") or "times").lower(), FONTS["times"])
    size = float(c.get("font_size") or 12)
    # Cap leading so a graduate CV with dot bullets still fits three A4 pages.
    ls = min(float(c.get("line_spacing") or 1.1), 1.12)
    lead = size * ls
    head = HEADING_COLORS.get((c.get("heading_color") or "black").lower(), colors.black)
    ink = colors.black
    gray = colors.HexColor("#333333")
    return {
        "name": ParagraphStyle("name", fontName=fam["bold"], fontSize=size + 2, leading=(size + 2) * 1.35, textColor=ink, spaceAfter=3, keepWithNext=True),
        "roles": ParagraphStyle("roles", fontName=fam["body"], fontSize=size, leading=lead, textColor=ink, spaceAfter=1, keepWithNext=True),
        "contact": ParagraphStyle("contact", fontName=fam["body"], fontSize=size, leading=lead, textColor=gray, spaceAfter=1, keepWithNext=True),
        "section": ParagraphStyle("section", fontName=fam["bold"], fontSize=size + 0.5, leading=(size + 0.5) * 1.25, textColor=head, spaceBefore=11, spaceAfter=3, keepWithNext=True),
        "subheading": ParagraphStyle("subheading", fontName=fam["bold"], fontSize=size, leading=lead, textColor=ink, spaceBefore=7, spaceAfter=1, keepWithNext=True),
        "body": ParagraphStyle("body", fontName=fam["body"], fontSize=size, leading=lead, spaceAfter=4, textColor=ink, splitLongWords=1),
        "bullet": ParagraphStyle("bullet", fontName=fam["body"], fontSize=size, leading=lead, leftIndent=18, bulletIndent=4, spaceAfter=2, textColor=ink, bulletFontName="Symbol", bulletFontSize=size * 0.9, splitLongWords=1),
    }


def _inline(t: str) -> str:
    t = (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)", r"\1", t)
    return t


SECTIONS = {
    "PROFILE", "SKILLS", "EXPERIENCE", "EDUCATION", "ACADEMIC PROJECT",
    "SELECTED PROJECTS", "ADDITIONAL INFORMATION", "REFERENCES",
}
SUBHEADINGS = {"Technical", "People and Communication"}


def _looks_like_heading(line: str) -> bool:
    t = line.strip()
    if not t or t.startswith(("http", "•", "- ")):
        return False
    if t.isupper() and len(t) < 70 and " " in t:
        return True
    if "," in t and re.search(r"\b(19|20)\d{2}\b", t) and len(t) < 120:
        return True
    if t.startswith(("Bachelor", "Diploma", "Certificate", "Master")):
        return True
    return False


def md_to_pdf(md_text: str, path: str):
    """Draft text -> A4 PDF. Plain headings are bold and well spaced; round dot
    bullets render as real dots with the Symbol font, never as control glyphs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.3*cm, bottomMargin=1.2*cm,
                            title=os.path.basename(path))
    S = _styles()
    story = []
    first = True
    for raw in (md_text or "").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 2))
            continue
        if first and stripped.startswith("# "):
            story.append(Paragraph(_inline(stripped[2:]), S["name"]))
            first = False
            continue
        if first:
            story.append(Paragraph(_inline(stripped), S["name"]))
            first = False
            continue
        if stripped.startswith("## "):
            story.append(Paragraph(_inline(stripped[3:]).upper(), S["section"]))
        elif stripped.startswith("### "):
            story.append(Paragraph(_inline(stripped[4:]), S["subheading"]))
        elif stripped.startswith("• ") or stripped.startswith("- "):
            # A single round dot at the start of a sentence. Symbol keeps the
            # glyph clean in both the page and extracted text.
            story.append(Paragraph(_inline(stripped[2:]), S["bullet"], bulletText="•"))
        elif stripped in SECTIONS:
            story.append(Paragraph(_inline(stripped), S["section"]))
        elif stripped in SUBHEADINGS or _looks_like_heading(stripped):
            story.append(Paragraph(_inline(stripped), S["subheading"]))
        else:
            story.append(Paragraph(_inline(stripped), S["body"]))
    doc.build(story)
    return path
