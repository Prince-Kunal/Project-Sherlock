"""MasterResume → Typst source (Jinja2) → PDF (`typst compile`). Follows every rule in PLAN.md §6.1.

`render_resume` also returns what was rendered (headings in order, bullet texts, contact details) so
`ats_check` can verify the PDF's extracted text against it.
"""

import asyncio
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.resume import Bullet, MasterResume

RESUME_DIR = Path(__file__).parent
FONTS_DIR = RESUME_DIR / "fonts"
TEMPLATES_DIR = RESUME_DIR / "templates"

SECTION_HEADINGS = {
    "education": "Education",
    "experience": "Experience",
    "projects": "Projects",
    "skills": "Skills",
    "achievements": "Achievements",
}
DEFAULT_SECTION_ORDER = ["education", "experience", "projects", "skills", "achievements"]

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_EN_DASH = "\u2013"
_SEP = " \u00b7 "  # middle dot
_TYPST_TIMEOUT_SECONDS = 30


class RenderError(Exception):
    pass


@dataclass
class RenderedResume:
    pdf: bytes
    name: str
    email: str | None
    phone: str | None
    headings: list[str]  # in rendered order
    bullets: list[str]  # every rendered bullet's text, as rendered
    typst_source: str = field(repr=False)


# --- text hygiene (§6.1: no emoji or decorative Unicode)

_KEEP_SYMBOLS = {"+", "#", "%", "&", "/", "@", "*", "=", "<", ">", "~", "|", "^", "$", "\u20b9"}
_LEADING_BULLET_RE = re.compile("^[\\s\\-\u2022\u25cf\u25aa\u25e6\u2023\u2043\u25a0\u25a1\u2219\u00b7*]+")


def clean_text(text: str) -> str:
    """NFKC-normalise (expands ligature glyphs like U+FB01 to "fi"), drop emoji/pictographs/arrows and
    other decorative symbols, strip leading bullet glyphs, and collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    kept = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == "So" or category in {"Cs", "Co", "Cn", "Cc", "Cf"}:
            if ch in "\n\t":
                kept.append(" ")
            continue
        if category == "Sk" and ch not in _KEEP_SYMBOLS:
            continue
        kept.append(ch)
    cleaned = " ".join("".join(kept).split())
    return _LEADING_BULLET_RE.sub("", cleaned).strip()


def typst_string(value: Any) -> str:
    """A Typst string literal: rendered as plain text, never parsed as markup."""
    text = clean_text("" if value is None else str(value))
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def format_date(value: str | None) -> str:
    if not value:
        return ""
    if value == "present":
        return "Present"
    year, _, month = value.partition("-")
    return f"{_MONTHS[int(month) - 1]} {year}" if month else year


def format_range(start: str | None, end: str | None) -> str:
    a, b = format_date(start), format_date(end)
    if a and b and a != b:
        return f"{a} {_EN_DASH} {b}"
    return a or b


def display_url(url: str) -> str:
    """Visible link text (§6.1: never hide a URL behind a word): scheme, www and trailing slash removed."""
    text = re.sub(r"^[a-z]+://", "", url.strip(), flags=re.IGNORECASE)
    text = re.sub(r"^www\.", "", text, flags=re.IGNORECASE)
    return text.rstrip("/")


def href(url: str) -> str:
    return url if re.match(r"^[a-z]+:", url, flags=re.IGNORECASE) else f"https://{url}"


def _join(*parts: str | None, sep: str = _SEP) -> str:
    return sep.join(p for p in (clean_text(p) if p else "" for p in parts) if p)


def _bullet_texts(bullets: list[Bullet]) -> list[str]:
    return [t for t in (clean_text(b.text) for b in bullets) if t]


def build_context(resume: MasterResume, section_order: list[str] | None = None) -> dict[str, Any]:
    basics = resume.basics
    contact: list[dict[str, str | None]] = []
    if basics.email:
        contact.append({"text": basics.email, "url": f"mailto:{basics.email}"})
    if basics.phone:
        contact.append({"text": basics.phone, "url": None})
    if basics.location:
        contact.append({"text": basics.location, "url": None})
    for link in basics.links:
        contact.append({"text": display_url(link.url), "url": href(link.url)})

    sections: list[dict[str, Any]] = []
    for key in section_order or DEFAULT_SECTION_ORDER:
        if key == "education" and resume.education:
            entries = [
                {
                    "title": _join(_join(e.degree, e.field, sep=", "), e.institution, sep=" \u2014 "),
                    "meta": _join(
                        e.location, format_range(e.start, e.end), f"GPA: {e.gpa}" if e.gpa else None
                    ),
                    "bullets": _bullet_texts(e.bullets),
                }
                for e in resume.education
            ]
            sections.append({"kind": "entries", "heading": SECTION_HEADINGS[key], "entries": entries})
        elif key == "experience" and resume.experience:
            entries = [
                {
                    "title": _join(e.role, e.org, sep=" \u2014 "),
                    "meta": _join(e.location, format_range(e.start, e.end)),
                    "bullets": _bullet_texts(e.bullets),
                }
                for e in resume.experience
            ]
            sections.append({"kind": "entries", "heading": SECTION_HEADINGS[key], "entries": entries})
        elif key == "projects" and resume.projects:
            entries = [
                {
                    "title": _join(p.name, display_url(p.link) if p.link else None, sep=" \u2014 "),
                    "meta": _join(", ".join(p.tech), format_range(p.start, p.end)),
                    "bullets": _bullet_texts(p.bullets),
                }
                for p in resume.projects
            ]
            sections.append({"kind": "entries", "heading": SECTION_HEADINGS[key], "entries": entries})
        elif key == "skills" and any(resume.skills.values()):
            lines = [
                {"category": clean_text(category), "joined": ", ".join(clean_text(i) for i in items)}
                for category, items in resume.skills.items()
                if items
            ]
            sections.append({"kind": "skills", "heading": SECTION_HEADINGS[key], "lines": lines})
        elif key == "achievements" and resume.achievements:
            entries = [{"title": "", "meta": "", "bullets": _bullet_texts(resume.achievements)}]
            sections.append({"kind": "entries", "heading": SECTION_HEADINGS[key], "entries": entries})

    return {
        "doc_title": f"{basics.name} — Resume",
        "basics": basics,
        "contact": contact,
        "summary": resume.summary,
        "sections": sections,
    }


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701 - output is Typst, and values are escaped by the `ts` filter
    )
    env.filters["ts"] = typst_string
    return env


_ENV = _environment()


def render_typst_source(resume: MasterResume, section_order: list[str] | None = None) -> str:
    return _ENV.get_template("resume.typ.j2").render(**build_context(resume, section_order))


async def compile_typst(source: str) -> bytes:
    """Compile Typst source to PDF with only the bundled fonts (identical output on every machine)."""
    with tempfile.TemporaryDirectory(prefix="sherlock-typst-") as tmp:
        src, out = Path(tmp) / "resume.typ", Path(tmp) / "resume.pdf"
        src.write_text(source, encoding="utf-8")
        process = await asyncio.create_subprocess_exec(
            "typst",
            "compile",
            "--root",
            tmp,
            "--font-path",
            str(FONTS_DIR),
            "--ignore-system-fonts",
            "--pdf-standard",
            "a-2b",
            str(src),
            str(out),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), _TYPST_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            process.kill()
            raise RenderError("typst compile timed out") from exc
        if process.returncode != 0:
            raise RenderError(f"typst compile failed: {stderr.decode(errors='replace')[:2000]}")
        return out.read_bytes()


async def render_resume(resume: MasterResume, section_order: list[str] | None = None) -> RenderedResume:
    context = build_context(resume, section_order)
    source = _ENV.get_template("resume.typ.j2").render(**context)
    pdf = await compile_typst(source)
    bullets = [b for s in context["sections"] for e in s.get("entries", []) for b in e["bullets"]]
    return RenderedResume(
        pdf=pdf,
        name=clean_text(resume.basics.name),
        email=resume.basics.email,
        phone=resume.basics.phone,
        headings=[s["heading"] for s in context["sections"]],
        bullets=bullets,
        typst_source=source,
    )


def resume_filename(name: str) -> str:
    """`Firstname_Lastname_Resume.pdf` (§6.1); no company name in the filename."""
    parts = [re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKD", p)) for p in name.split()]
    parts = [p for p in parts if p]
    return "_".join([*(parts[:1] + parts[-1:] if len(parts) > 1 else parts), "Resume"]) + ".pdf"
