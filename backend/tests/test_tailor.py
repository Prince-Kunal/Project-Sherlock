"""Phase 4 acceptance: the validator rules (incl. adversarial cases), a valid plan → 1-page PDF with a
correct diff, the overflow-trimming loop, the JD keyword rule, and every tailored PDF passing ats_check."""

import io
from typing import Any

import pdfplumber
import pytest

from app.models import Company, Job
from app.schemas.resume import Bullet, Experience, MasterResume
from app.schemas.tailor import Rephrasing, TailorPlan
from app.services.llm.fake import FakeLLMClient
from app.services.resume import assemble as assemble_module
from app.services.resume import tailor as tailor_module
from app.services.resume.assemble import (
    MAX_RENDER_ATTEMPTS,
    PageOverflowError,
    TailoredDraft,
    apply_plan,
    render_one_page,
)
from app.services.resume.ats_check import AtsExpectations, AtsReport, ats_check
from app.services.resume.skills import get_lexicon
from app.services.resume.tailor import Tailor, TailorError
from app.services.resume.validator import new_numbers, validate_plan
from tests.tailor_fixtures import JD, master, valid_plan


def codes(plan: TailorPlan, resume: MasterResume | None = None) -> list[str]:
    return [i.code for i in validate_plan(plan, resume or master(), get_lexicon())]


def rephrase(bullet_id: str, text: str, **overrides: Any) -> TailorPlan:
    return valid_plan(rephrasings=[Rephrasing(bullet_id=bullet_id, text=text)], **overrides)


def pdf_text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


# --- Validator ---------------------------------------------------------------------------------------


def test_valid_plan_has_no_issues() -> None:
    assert codes(valid_plan()) == []


def test_unknown_bullet_id_rejected() -> None:
    plan = valid_plan(selected_bullet_ids=["exp1-b1", "exp9-b1"])
    issues = validate_plan(plan, master(), get_lexicon())
    assert [(i.code, i.bullet_id) for i in issues] == [("unknown_bullet", "exp9-b1")]
    assert codes(rephrase("nope", "text")) == ["unknown_bullet"]
    assert codes(valid_plan(selected_bullet_ids=["exp1"])) == [
        "unknown_bullet",
        "no_bullets",
        "pinned_missing",
    ]


def test_pinned_bullet_required_only_when_its_section_is_shown() -> None:
    without_pinned = ["exp1-b2", "proj2-b1"]
    assert codes(valid_plan(selected_bullet_ids=without_pinned)) == ["pinned_missing"]
    no_experience = valid_plan(
        selected_bullet_ids=["proj2-b1"], section_order=["education", "projects", "skills"]
    )
    assert codes(no_experience) == []


@pytest.mark.parametrize(
    "text",
    [
        "Cut p95 latency by 30% with Redis caching on Kubernetes",  # injected skill
        "Cut p95 latency by 30% with Redis caching on K8s",  # ...under an alias
        "Cut p95 latency by 30% with Redis and Kafka",
    ],
)
def test_injected_skill_rejected(text: str) -> None:
    assert codes(rephrase("exp1-b2", text)) == ["new_skill"]


def test_skill_from_the_master_resume_is_allowed() -> None:
    # Docker isn't in this bullet's tags but is in the master's skills (PLAN.md: bullet skills or master skills).
    assert codes(rephrase("exp1-b2", "Cut p95 latency by 30% with Redis caching, shipped in Docker")) == []


def test_everyday_words_are_not_mistaken_for_skills() -> None:
    assert codes(rephrase("exp1-b3", "Raised test coverage from 55% to 80% ahead of the go live")) == []


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("Improved p95 latency by 40% with Redis caching", "40%"),  # changed number
        ("Cut p95 latency by 30% for 2,000 users with Redis caching", "2000"),  # new number
        ("Cut p95 latency by half with Redis caching", "50%"),  # number in words
    ],
)
def test_new_or_changed_number_rejected(text: str, bad: str) -> None:
    plan = rephrase("exp1-b2", text)
    assert codes(plan) == ["new_number"]
    assert bad in validate_plan(plan, master(), get_lexicon())[0].message


def test_numbers_may_be_reformatted() -> None:
    assert new_numbers("Cut latency 30 percent", "cutting p95 latency by 30%") == []
    assert new_numbers("Served 1,200 users", "Served 1200 users") == []
    assert new_numbers("A team of three", "A team of 3") == []


def test_rephrasing_longer_than_1_3x_rejected() -> None:
    original = master().experience[0].bullets[1].text
    long = "Cut p95 latency by 30% with Redis caching " + "x" * len(original)
    assert codes(rephrase("exp1-b2", long)) == ["too_long"]


def test_skills_to_show_must_come_from_master() -> None:
    assert codes(valid_plan(skills_to_show=["Python", "Kubernetes"])) == ["unknown_skill_shown"]
    assert codes(valid_plan(skills_to_show=["PostgreSQL", "Python"])) == []  # alias of master "postgres"


def test_summary_rules() -> None:
    assert codes(valid_plan(summary="Python backend student")) == []
    assert codes(valid_plan(summary="Student with 3 years of Python")) == ["new_number"]
    assert codes(valid_plan(summary="Student who builds Python and Go services")) == ["new_skill"]
    no_summary = master().model_copy(update={"summary": None})
    assert codes(valid_plan(summary="Anything"), no_summary) == ["summary_not_allowed"]


# --- A valid plan → 1-page PDF, correct diff, keyword rule, ATS --------------------------------------


async def test_valid_plan_renders_one_page_with_correct_diff_and_keywords() -> None:
    result = await Tailor(FakeLLMClient()).build(master(), valid_plan(), JD)

    assert result.ats.passed, result.ats.failures
    assert result.ats.page_count == 1
    assert result.dropped_to_fit == []

    diff = {(c.bullet_id, c.change): (c.before, c.after) for c in result.diff}
    assert set(diff) == {
        ("exp1-b1", "rephrased"),  # only the JD respelling: postgres → PostgreSQL
        ("exp1-b2", "rephrased"),
        ("exp1-b3", "reordered"),
        ("proj1-b2", "removed"),
        ("ach1", "removed"),
    }
    assert diff[("exp1-b1", "rephrased")][1] == (
        "Built REST APIs in Python and Flask backed by PostgreSQL for merchant onboarding"
    )
    assert diff[("proj1-b2", "removed")] == ("Designed the matching service with geohash bucketing", None)

    # Projects ordered by their best bullet; experience bullets by rank.
    assert [p.id for p in result.resume.projects] == ["proj2", "proj1"]
    assert [b.id for b in result.resume.experience[0].bullets] == ["exp1-b1", "exp1-b3", "exp1-b2"]

    # Keyword rule: JD spelling for a skill the user has; a missing skill is reported, never printed.
    text = pdf_text(result.rendered.pdf)
    assert "PostgreSQL" in text
    assert "postgres," not in text.lower().replace("postgresql", "")
    assert "Kubernetes" not in text
    assert result.swaps == {"postgresql": "PostgreSQL", "python": "Python", "redis": "Redis"}
    assert result.keyword_coverage.matched == ["Python", "PostgreSQL", "Redis"]
    assert result.keyword_coverage.missing == ["Kubernetes"]
    assert result.keyword_coverage.score == 0.75


async def test_without_llm_keywords_the_jd_is_scanned_for_known_skills() -> None:
    result = await Tailor(FakeLLMClient()).build(master(), valid_plan(jd_keywords=[]), JD)
    assert set(result.keyword_coverage.matched) >= {"Python", "PostgreSQL", "Redis", "Docker"}
    assert "Kubernetes" in result.keyword_coverage.missing


def test_fallback_jd_scan_ignores_skill_names_that_are_also_words() -> None:
    from app.services.resume.assemble import jd_must_haves

    jd = "Go beyond the basics. You will Express ideas clearly and write Python and Go services."
    assert jd_must_haves(jd, [], get_lexicon()) == ["Python"]
    assert jd_must_haves(jd, ["Go", "Python"], get_lexicon()) == ["Go", "Python"]  # the LLM can name them


async def test_llm_keywords_not_in_the_jd_are_ignored() -> None:
    plan = valid_plan(jd_keywords=["Python", "Rust"])  # Rust isn't in the JD
    result = await Tailor(FakeLLMClient()).build(master(), plan, JD)
    assert result.keyword_coverage.matched + result.keyword_coverage.missing == ["Python"]


async def test_build_refuses_an_unvalidated_plan() -> None:
    with pytest.raises(TailorError) as caught:
        await Tailor(FakeLLMClient()).build(master(), rephrase("exp1-b2", "Scaled Kubernetes 40%"), JD)
    assert caught.value.reason == "validation_failed"


# --- Overflow trimming -------------------------------------------------------------------------------


def _long_master(bullets: int, pinned: int = 1) -> MasterResume:
    base = master()
    text = (
        "Designed and shipped an internal reporting service in Python and Flask that replaced manual "
        "spreadsheets, with role-based access and audit logs for the finance team number {n}"
    )
    long_bullets = [
        Bullet(id=f"exp2-b{n}", text=text.format(n=n), skills=["python", "flask"], pinned=n <= pinned)
        for n in range(1, bullets + 1)
    ]
    extra = Experience(id="exp2", org="Example Corp", role="Software Intern", bullets=long_bullets)
    return base.model_copy(update={"experience": [*base.experience, extra]})


async def test_overflow_drops_lowest_ranked_non_pinned_bullets_until_one_page() -> None:
    resume = _long_master(bullets=30, pinned=2)
    ranking = ["exp1-b1", *(f"exp2-b{n}" for n in range(1, 31)), "proj2-b1", "edu1-b1"]
    plan = valid_plan(selected_bullet_ids=ranking)
    draft = apply_plan(resume, plan, get_lexicon())

    rendered, dropped = await render_one_page(draft)

    report = await ats_check(rendered.pdf, AtsExpectations.from_rendered(rendered))
    assert report.passed, report.failures
    assert report.page_count == 1
    assert dropped, "the long resume should have needed trimming"
    # Dropped from the bottom of the ranking, skipping pinned ones.
    pinned = {"exp1-b1", "exp2-b1", "exp2-b2"}
    assert dropped == [b for b in reversed(ranking) if b not in pinned][: len(dropped)]
    kept = {b.id for b in draft.resume.all_bullets()}
    assert {"exp1-b1", "exp2-b1", "exp2-b2"} <= kept


async def test_overflow_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    renders = 0
    real = assemble_module.render_resume

    async def counting_render(*args: Any, **kwargs: Any) -> Any:
        nonlocal renders
        renders += 1
        return await real(*args, **kwargs)

    monkeypatch.setattr("app.services.resume.assemble.render_resume", counting_render)
    monkeypatch.setattr("app.services.resume.assemble.overflow", lambda pdf: (2, 3))  # never fits
    ranking = ["exp1-b1", *(f"exp2-b{n}" for n in range(1, 31))]
    draft = apply_plan(_long_master(bullets=30), valid_plan(selected_bullet_ids=ranking), get_lexicon())
    with pytest.raises(PageOverflowError):
        await render_one_page(draft)
    assert renders == MAX_RENDER_ATTEMPTS


async def test_overflow_with_only_pinned_bullets_fails_fast() -> None:
    resume = _long_master(bullets=30, pinned=30)
    plan = valid_plan(selected_bullet_ids=["exp1-b1", *(f"exp2-b{n}" for n in range(1, 31))])
    draft = apply_plan(resume, plan, get_lexicon())
    with pytest.raises(PageOverflowError):
        await render_one_page(draft)
    with pytest.raises(TailorError) as caught:
        await Tailor(FakeLLMClient()).build(resume, plan, JD)
    assert caught.value.reason == "page_overflow"


# --- ATS failure blocks the PDF (invariant 11) -------------------------------------------------------


async def test_failing_ats_check_is_retried_once_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def failing(pdf: bytes, expect: AtsExpectations) -> AtsReport:
        nonlocal calls
        calls += 1
        return AtsReport(passed=False, failures=["pdftotext: name not found"], page_count=1)

    monkeypatch.setattr(tailor_module, "ats_check", failing)
    with pytest.raises(TailorError) as caught:
        await Tailor(FakeLLMClient()).build(master(), valid_plan(), JD)
    assert caught.value.reason == "ats_check_failed"
    assert calls == 2


# --- LLM plan with one validator retry ---------------------------------------------------------------


def _job() -> tuple[Job, Company]:
    company = Company(name="Ledgerline", domain="ledgerline.example")
    job = Job(
        title="Backend Engineering Intern", location="Bengaluru", description_text=JD, dedupe_hash="x" * 64
    )
    return job, company


async def test_plan_is_retried_once_with_the_issues() -> None:
    bad = rephrase("exp1-b2", "Improved p95 latency by 40% with Redis caching")
    llm = FakeLLMClient(responses={"tailor": [bad.model_dump(), valid_plan().model_dump()]})
    job, company = _job()

    plan = await Tailor(llm).plan(master(), job, company, "key")

    assert plan == valid_plan()
    first, second = (prompt for request, prompt in llm.calls)
    assert "(none)" in first
    assert "[new_number] exp1-b2: uses 40%" in second
    assert all(request.tier == "smart" and request.allow_fallback for request, _ in llm.calls)


async def test_plan_failing_twice_raises() -> None:
    bad = rephrase("exp1-b2", "Scaled it on Kubernetes")
    llm = FakeLLMClient(responses={"tailor": [bad.model_dump()]})
    job, company = _job()
    with pytest.raises(TailorError) as caught:
        await Tailor(llm).plan(master(), job, company, "key")
    assert caught.value.reason == "validation_failed"
    assert [i.code for i in caught.value.issues] == ["new_skill"]
    assert len(llm.calls) == 2


async def test_tailor_prompt_has_no_personal_details() -> None:
    llm = FakeLLMClient(responses={"tailor": [valid_plan().model_dump()]})
    job, company = _job()
    await Tailor(llm).plan(master(), job, company, "key")
    [(_, prompt)] = llm.calls
    for secret in ("Asha Verma", "asha.verma@example.com", "98765", 'github.com/ashaverma"'):
        assert secret not in prompt
    assert '"exp1-b2"' in prompt  # bullet ids are there to select from


def test_draft_keeps_basics_and_education_always() -> None:
    plan = valid_plan(section_order=["experience", "projects"])
    draft: TailoredDraft = apply_plan(master(), plan, get_lexicon())
    assert draft.section_order[0] == "education"
    assert draft.resume.basics == master().basics


def test_naming_the_bullets_own_entry_is_not_a_new_skill() -> None:
    base = master()
    renamed = base.projects[1].model_copy(update={"name": "Kafka Log Summarizer"})
    resume = base.model_copy(update={"projects": [base.projects[0], renamed]})
    text = "Containerised the Kafka log summarisation pipeline with Docker"
    assert codes(rephrase("proj2-b1", text), resume) == []
    # The same word in another entry's bullet is new information there.
    assert codes(rephrase("exp1-b2", "Cut p95 latency by 30% with Redis caching and Kafka"), resume) == [
        "new_skill"
    ]


# --- A real recorded plan, end to end ----------------------------------------------------------------


async def test_recorded_real_plan_tailors_the_fixture_resume() -> None:
    from tests.conftest import recorded
    from tests.matching_fixtures import fixture_jobs, fixture_resume, unsaved_job

    attempts = recorded("tailor", "rohan_ledgerline")
    llm = FakeLLMClient(responses={"tailor": attempts})
    job, company = unsaved_job(next(i for i in fixture_jobs() if i["key"] == "relevant"))
    resume = fixture_resume()

    result = await Tailor(llm).tailor(resume, job, company, "key")

    assert result.ats.passed, result.ats.failures
    assert result.ats.page_count == 1
    assert result.filename == "Rohan_Das_Resume.pdf"
    assert {"Python", "Django", "PostgreSQL", "Docker"} <= set(result.keyword_coverage.matched)
    # Nothing in the tailored resume is absent from the master (invariant 2), checked independently:
    master_texts = {b.id: b.text for b in resume.all_bullets()}
    rephrased = {c.bullet_id for c in result.diff if c.change == "rephrased"}
    for bullet in result.resume.all_bullets():
        assert bullet.id in master_texts
        if bullet.id not in rephrased:
            assert bullet.text == master_texts[bullet.id]


async def test_pdf_stored_under_user_and_outreach_with_recipient_filename(storage_dir: Any) -> None:
    import uuid

    from app.services.resume.files import find_pdf, save_tailored_pdf

    user_id, outreach_id = uuid.uuid4(), uuid.uuid4()
    result = await Tailor(FakeLLMClient()).build(master(), valid_plan(), JD)
    path = await save_tailored_pdf(user_id, str(outreach_id), result.filename, result.rendered.pdf)
    assert path == storage_dir / str(user_id) / str(outreach_id) / "Asha_Verma_Resume.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    assert find_pdf(user_id, str(outreach_id)) == path
