"""Phase 1 acceptance: preview PDFs render to 1 page and pass ats_check for every fixture resume;
ats_check fails the deliberately broken fixtures (two-column, ligatures, image-only, header contact)."""

import io
import json
from pathlib import Path

import pdfplumber
import pytest
from httpx import AsyncClient

from app.schemas.resume import MasterResume, ParsedResume
from app.services.resume.ats_check import AtsExpectations, ats_check, keyword_coverage
from app.services.resume.parser import build_master_resume, profile_links
from app.services.resume.render import (
    clean_text,
    format_range,
    render_resume,
    render_typst_source,
    resume_filename,
)
from app.services.resume.skills import get_lexicon
from tests.conftest import FIXTURES, recorded

ATS = FIXTURES / "ats"
FIXTURE_RESUMES = ["aarav_menon", "meera_iyer", "rohan_das"]


def _fixture_master(name: str) -> MasterResume:
    parsed = ParsedResume.model_validate(recorded("parse_resume", name))
    return build_master_resume(
        parsed,
        email=f"{name.replace('_', '.')}@example.com",
        phone="+91 90000 12345",
        found_links=profile_links([link.url for link in parsed.basics.links]),
        lexicon=get_lexicon(),
    )


def _text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


@pytest.mark.parametrize("name", FIXTURE_RESUMES)
async def test_fixture_resume_renders_one_page_and_passes_ats(name: str) -> None:
    rendered = await render_resume(_fixture_master(name))
    report = await ats_check(rendered.pdf, AtsExpectations.from_rendered(rendered))
    assert report.page_count == 1
    assert report.passed, report.failures


async def test_rendered_pdf_metadata_and_layout_rules() -> None:
    resume = _fixture_master("meera_iyer")
    rendered = await render_resume(resume)
    with pdfplumber.open(io.BytesIO(rendered.pdf)) as doc:
        assert doc.metadata["Title"] == "Meera Iyer — Resume"
        assert doc.metadata["Author"] == "Meera Iyer"
        fonts = {c["fontname"].split("+")[-1] for c in doc.pages[0].chars}
        sizes = {round(c["size"], 1) for c in doc.pages[0].chars}
    assert all(f.startswith("SourceSans3") for f in fonts), fonts
    assert 18.0 in sizes  # name 16-20pt
    assert {s for s in sizes if s < 16} <= {10.5, 12.0}  # body 10-11pt, headings 12pt
    # Standard headings only, in order; no creative names like "Work Experience" or "Publications".
    assert rendered.headings == ["Education", "Experience", "Projects", "Skills", "Achievements"]
    text = _text(rendered.pdf)
    assert "\u25cf" not in text  # the resume's heavy bullet glyphs are gone
    assert "\u2197" not in text  # and so are the "GitHub ↗" arrows
    assert "github.com/meeraiyer/picker-sim" in text  # project link written out as visible text


async def test_links_are_visible_text_and_hyperlinked() -> None:
    rendered = await render_resume(_fixture_master("aarav_menon"))
    text = _text(rendered.pdf)
    assert "linkedin.com/in/aarav-menon-dev" in text  # was hidden behind "LinkedIn" in the original
    with pdfplumber.open(io.BytesIO(rendered.pdf)) as doc:
        targets = {h["uri"] for h in doc.pages[0].hyperlinks}
    assert "https://www.linkedin.com/in/aarav-menon-dev" in targets


async def test_user_text_cannot_inject_typst_markup() -> None:
    resume = _fixture_master("rohan_das")
    nasty = 'Used #import("x") and *bold* _it_ $x$ <label> @ref // comment \\ "quoted" -- ok'
    resume.achievements[0].text = nasty
    source = render_typst_source(resume)
    assert '#import("x")' not in source.replace('\\"', '"').split("#list(")[0]
    rendered = await render_resume(resume)
    assert nasty in _text(rendered.pdf).replace("\n", " ")


def test_dates_use_one_format() -> None:
    assert format_range("2025-01", "present") == "Jan 2025 – Present"
    assert format_range("2024", "2028") == "2024 – 2028"
    assert format_range("2026-06", None) == "Jun 2026"
    assert format_range(None, "2024") == "2024"
    assert format_range(None, None) == ""


def test_clean_text_strips_decoration_but_keeps_meaning() -> None:
    assert clean_text("● Built an API \U0001f680 in C++ & C#") == "Built an API in C++ & C#"
    assert clean_text("eﬃcient ﬁle") == "efficient file"  # ligature code points expanded
    assert clean_text("cut costs by 40% (₹2L)") == "cut costs by 40% (₹2L)"


def test_resume_filename() -> None:
    assert resume_filename("Meera Iyer") == "Meera_Iyer_Resume.pdf"
    assert resume_filename("John Abraham V") == "John_V_Resume.pdf"
    assert resume_filename("Priyá") == "Priya_Resume.pdf"


async def test_preview_endpoints(with_llm_key: AsyncClient, fake_llm: object) -> None:
    from app.services.llm.fake import FakeLLMClient

    assert isinstance(fake_llm, FakeLLMClient)
    fake_llm.add_response("parse_resume", recorded("parse_resume", "aarav_menon"))
    path = FIXTURES / "resumes" / "aarav_menon.pdf"
    await with_llm_key.post(
        "/resume/upload", files={"file": (path.name, path.read_bytes(), "application/pdf")}
    )

    pdf = await with_llm_key.get("/resume/preview.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert 'filename="Aarav_Menon_Resume.pdf"' in pdf.headers["content-disposition"]
    assert pdf.headers["x-ats-passed"] == "true"
    assert pdf.content.startswith(b"%PDF")

    report = (await with_llm_key.get("/resume/ats-check")).json()
    assert report == {"passed": True, "failures": [], "page_count": 1, "keyword_coverage": None}


# --- ats_check against committed fixtures ----------------------------------------------------------


@pytest.fixture
def expectations() -> AtsExpectations:
    return AtsExpectations(**json.loads((ATS / "expectations.json").read_text()))


def _pdf(name: str) -> bytes:
    return (ATS / f"{name}.pdf").read_bytes()


async def test_valid_fixture_passes(expectations: AtsExpectations) -> None:
    report = await ats_check(_pdf("valid"), expectations)
    assert report.passed, report.failures


async def test_two_column_layout_fails(expectations: AtsExpectations) -> None:
    report = await ats_check(_pdf("two_column"), expectations)
    assert not report.passed
    assert any("not extracted intact" in f or "out of order" in f for f in report.failures)


async def test_ligature_code_points_fail(expectations: AtsExpectations) -> None:
    report = await ats_check(_pdf("ligatures"), expectations)
    assert not report.passed
    assert any("ligature characters" in f for f in report.failures)


async def test_image_only_scan_fails(expectations: AtsExpectations) -> None:
    report = await ats_check(_pdf("image_only"), expectations)
    assert not report.passed
    assert "PDF has no text layer" in report.failures
    assert "PDF contains images" in report.failures


async def test_contact_only_in_page_header_fails(expectations: AtsExpectations) -> None:
    report = await ats_check(_pdf("header_contact"), expectations)
    assert not report.passed
    assert any("email not found" in f for f in report.failures)
    assert any("phone not found" in f for f in report.failures)


async def test_multi_page_pdf_fails(expectations: AtsExpectations) -> None:
    from app.services.resume.render import compile_typst

    source = '#set page(paper: "a4")\nPage one.\n#pagebreak()\nPage two.\n'
    report = await ats_check(await compile_typst(source), expectations)
    assert "PDF has 2 pages; must be 1" in report.failures


def test_keyword_coverage_reports_matches_and_gaps() -> None:
    text = "Built APIs in Python with PostgreSQL and C++; deployed on GCP."
    coverage = keyword_coverage(text, ["PostgreSQL", "python", "C++", "C", "Kubernetes"])
    assert coverage.matched == ["PostgreSQL", "python", "C++"]
    assert coverage.missing == ["C", "Kubernetes"]  # "C" must not match inside "C++"
    assert coverage.score == pytest.approx(0.6)


def test_fixture_sources_exist() -> None:
    """The binary fixtures are reproducible: see tests/fixtures/build_fixtures.py."""
    for name in ("aarav_menon.typ", "meera_iyer.typ"):
        assert (FIXTURES / "resumes" / "src" / name).exists()
    assert Path(FIXTURES / "build_fixtures.py").exists()
