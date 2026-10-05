"""Automated ATS check (PLAN.md §6.1). Runs on every PDF Sherlock produces; a failure blocks the PDF
from being attached anywhere (invariant 11).

Text is extracted twice, with pdfplumber and poppler's `pdftotext`, and every rule is checked against
both. pdfplumber's extraction leaves out content tagged as a PDF Artifact (page headers/footers), so
contact details that only exist in a page header are caught.
"""

import asyncio
import io
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from pydantic import BaseModel

from app.services.resume.render import RenderedResume

CONTACT_WINDOW = 0.15  # contact details must appear in the first 15% of the extracted text
_BAD_SEQUENCES = ("(cid:",)
_LIGATURES = {chr(cp) for cp in range(0xFB00, 0xFB07)}
_REPLACEMENT_CHAR = "�"
_PDFTOTEXT_TIMEOUT_SECONDS = 30


@dataclass
class AtsExpectations:
    name: str
    email: str | None
    phone: str | None
    headings: list[str]  # in rendered order
    bullets: list[str]
    keywords: list[str] = field(default_factory=list)  # JD must-haves, for the coverage report

    @classmethod
    def from_rendered(cls, rendered: RenderedResume, keywords: list[str] | None = None) -> "AtsExpectations":
        return cls(
            name=rendered.name,
            email=rendered.email,
            phone=rendered.phone,
            headings=rendered.headings,
            bullets=rendered.bullets,
            keywords=list(keywords or []),
        )


class KeywordCoverage(BaseModel):
    score: float  # matched / total, 0..1
    matched: list[str]
    missing: list[str]


class AtsReport(BaseModel):
    passed: bool
    failures: list[str]
    page_count: int
    keyword_coverage: KeywordCoverage | None = None


@dataclass
class _PdfFacts:
    page_count: int
    has_images: bool
    body_text: str  # pdfplumber, Artifact-tagged content excluded


def _read_pdf(pdf: bytes) -> _PdfFacts:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        texts = []
        has_images = False
        for page in doc.pages:
            has_images = has_images or bool(page.images)
            body = page.filter(lambda obj: obj.get("tag") != "Artifact")
            # expand_ligatures=False: report ligature code points instead of silently fixing them.
            texts.append(body.extract_text(expand_ligatures=False) or "")
        return _PdfFacts(page_count=len(doc.pages), has_images=has_images, body_text="\n".join(texts))


async def _pdftotext(pdf: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="sherlock-ats-") as tmp:
        path = Path(tmp) / "resume.pdf"
        path.write_bytes(pdf)
        process = await asyncio.create_subprocess_exec(
            "pdftotext",
            "-enc",
            "UTF-8",
            str(path),
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), _PDFTOTEXT_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            raise
        if process.returncode != 0:
            raise RuntimeError(f"pdftotext failed: {stderr.decode(errors='replace')[:500]}")
        return stdout.decode("utf-8", errors="replace")


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _squash(text: str) -> str:
    """Remove all whitespace: robust to line wraps (including at hyphens) but not to reordered text."""
    return "".join(text.split())


def _phone_pattern(phone: str) -> re.Pattern[str] | None:
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    return re.compile(r"\D{0,3}".join(digits))


def _check_text(source: str, text: str, expect: AtsExpectations) -> list[str]:
    failures: list[str] = []

    # Rule 2: unmappable glyphs, ligature code points, replacement characters.
    if any(seq in text for seq in _BAD_SEQUENCES):
        failures.append(f"{source}: contains (cid:) sequences (font without a Unicode mapping)")
    if found := sorted({ch for ch in text if ch in _LIGATURES}):
        failures.append(
            f"{source}: contains ligature characters {', '.join(f'U+{ord(c):04X}' for c in found)}"
        )
    if _REPLACEMENT_CHAR in text:
        failures.append(f"{source}: contains U+FFFD replacement characters")

    # Rule 3: name, email and phone in the first 15% of the text.
    collapsed = _collapse(text)
    window = collapsed[: max(1, math.ceil(len(collapsed) * CONTACT_WINDOW))]
    if _collapse(expect.name).lower() not in window.lower():
        failures.append(f"{source}: name not found in the first 15% of the text")
    if expect.email and expect.email.lower() not in window.lower():
        failures.append(f"{source}: email not found in the first 15% of the text")
    if expect.phone and (pattern := _phone_pattern(expect.phone)) and not pattern.search(window):
        failures.append(f"{source}: phone not found in the first 15% of the text")

    # Rule 4: section headings present, as their own lines, in the rendered order.
    lines = [line.strip().lower() for line in text.splitlines()]
    positions = []
    for heading in expect.headings:
        try:
            positions.append(lines.index(heading.lower()))
        except ValueError:
            failures.append(f"{source}: section heading {heading!r} not found")
    if len(positions) == len(expect.headings) and positions != sorted(positions):
        failures.append(f"{source}: section headings are out of order")

    # Rule 5: every bullet's text is present intact (catches multi-column layouts and broken reading order).
    squashed = _squash(text)
    missing = [b for b in expect.bullets if _squash(b) not in squashed]
    if missing:
        preview = "; ".join(m[:60] for m in missing[:3])
        failures.append(f"{source}: {len(missing)} bullet(s) not extracted intact, e.g. {preview}")
    return failures


def keyword_coverage(text: str, keywords: list[str]) -> KeywordCoverage:
    matched: list[str] = []
    missing: list[str] = []
    for keyword in keywords:
        pattern = re.compile(rf"(?<![\w+#.]){re.escape(keyword)}(?![\w+#])", re.IGNORECASE)
        (matched if pattern.search(text) else missing).append(keyword)
    score = len(matched) / len(keywords) if keywords else 1.0
    return KeywordCoverage(score=score, matched=matched, missing=missing)


async def ats_check(pdf: bytes, expect: AtsExpectations) -> AtsReport:
    facts = await asyncio.to_thread(_read_pdf, pdf)
    failures: list[str] = []

    # Rule 6: one page, no images, has a text layer.
    if facts.page_count > 1:
        failures.append(f"PDF has {facts.page_count} pages; must be 1")
    if facts.has_images:
        failures.append("PDF contains images")
    if not facts.body_text.strip():
        failures.append("PDF has no text layer")
        return AtsReport(passed=False, failures=failures, page_count=facts.page_count)

    failures += _check_text("pdfplumber", facts.body_text, expect)
    failures += _check_text("pdftotext", await _pdftotext(pdf), expect)

    # Rule 7: report (never fail on) keyword coverage.
    coverage = keyword_coverage(facts.body_text, expect.keywords) if expect.keywords else None
    return AtsReport(
        passed=not failures, failures=failures, page_count=facts.page_count, keyword_coverage=coverage
    )
