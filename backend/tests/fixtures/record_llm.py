"""Record real LLM outputs for fixtures, for the FakeLLMClient to replay in tests.

Run from backend/ with a real GEMINI_API_KEY in .env (one fast-model request per item):
    uv run python -m tests.fixtures.record_llm            # resumes (parse_resume)
    uv run python -m tests.fixtures.record_llm hn         # HN thread fixture (parse_hn_comment)
    uv run python -m tests.fixtures.record_llm match      # matching fixture jobs (match)
    uv run python -m tests.fixtures.record_llm tailor     # Rohan's resume for the Ledgerline intern job (smart)
    uv run python -m tests.fixtures.record_llm draft      # the referral email for that job (smart)
    uv run python -m tests.fixtures.record_llm match_company  # Rohan vs the YC fixture companies
    uv run python -m tests.fixtures.record_llm tailor_open    # Rohan's resume for Abstra, no job (smart)
    uv run python -m tests.fixtures.record_llm draft_open     # the open-outreach email to Abstra (smart)

Re-run whenever the corresponding prompt changes version.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.core.redis import get_redis
from app.schemas.resume import ParsedResume
from app.services.llm.gemini import GeminiClient
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.rate_limit import RateLimiter
from app.services.llm.redaction import redact_pii
from app.services.resume.parser import build_parse_prompt, extract_document, find_urls
from app.services.sources.hn import HNJob
from app.services.sources.text import html_to_text

if TYPE_CHECKING:
    from app.services.email.drafter import DraftInputs, OpenDraftInputs

FIXTURES = Path(__file__).parent
RESUMES = FIXTURES / "resumes"
RECORDED = FIXTURES / "llm" / "parse_resume"
FIXTURE_FILES = ["aarav_menon.pdf", "meera_iyer.pdf", "rohan_das.docx"]


def _client() -> GeminiClient:
    settings = get_settings()
    return GeminiClient(
        default_api_key=settings.gemini_api_key,
        model_smart=settings.llm_model_smart,
        model_fast=settings.llm_model_fast,
        limiter=RateLimiter(get_redis(), rpm=settings.llm_rpm, rpd=settings.llm_rpd),
    )


async def record_hn() -> None:
    thread = json.loads((FIXTURES / "sources" / "hn" / "thread.json").read_text())
    comments = [
        {"comment_id": c["id"], "text": redact_pii(html_to_text(c["text"]))[:4000]}
        for c in thread["children"]
    ]
    prompt = load_prompt("parse_hn_comment")
    request = prompt.request(tier="fast", comments=json.dumps(comments, ensure_ascii=False))
    request = type(request)(**{**request.__dict__, "use_cache": False})
    jobs = await _client().generate(request, list[HNJob])
    out = FIXTURES / "llm" / "parse_hn_comment" / "thread.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([j.model_dump() for j in jobs], indent=2) + "\n")
    print(f"recorded {out.relative_to(FIXTURES)} ({len(jobs)} jobs, prompt v{prompt.version})")


async def record_match() -> None:
    from app.services.matching.profile import candidate_payload
    from app.services.matching.rerank import Reranker, job_payload
    from tests.matching_fixtures import FIXTURE_PREFS, SCORED_KEYS, fixture_jobs, fixture_resume, unsaved_job

    candidate = candidate_payload(FIXTURE_PREFS, fixture_resume())
    jobs = [unsaved_job(item) for item in fixture_jobs() if item["key"] in SCORED_KEYS]
    scores = await Reranker(_client()).request_scores(
        candidate, [job_payload(job, company) for job, company in jobs], None
    )
    out = FIXTURES / "llm" / "match" / "fixture_jobs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([s.model_dump() for s in scores.values()], indent=2) + "\n")
    print(f"recorded {out.relative_to(FIXTURES)} ({len(scores)} of {len(jobs)} jobs scored)")


async def record_tailor() -> None:
    """Records every attempt (the validator may reject the first) so tests replay the real sequence."""
    from app.schemas.tailor import TailorPlan
    from app.services.resume.skills import get_lexicon
    from app.services.resume.tailor import Tailor
    from app.services.resume.validator import validate_plan
    from tests.matching_fixtures import fixture_jobs, fixture_resume, unsaved_job

    class Recording(GeminiClient):
        plans: list[TailorPlan] = []  # noqa: RUF012

        async def generate(self, request, output_type, **kwargs):  # type: ignore[no-untyped-def]
            plan = await super().generate(request, output_type, **kwargs)
            self.plans.append(plan)
            return plan

    settings = get_settings()
    client = Recording(
        default_api_key=settings.gemini_api_key,
        model_smart=settings.llm_model_smart,
        model_fast=settings.llm_model_fast,
        limiter=RateLimiter(get_redis(), rpm=settings.llm_rpm, rpd=settings.llm_rpd),
    )
    job, company = unsaved_job(next(i for i in fixture_jobs() if i["key"] == "relevant"))
    resume = fixture_resume()
    try:
        await Tailor(client).plan(resume, job, company, None)
    finally:
        out = FIXTURES / "llm" / "tailor" / "rohan_ledgerline.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([p.model_dump() for p in client.plans], indent=2) + "\n")
        for i, plan in enumerate(client.plans, 1):
            print(f"attempt {i}: issues={[x.code for x in validate_plan(plan, resume, get_lexicon())]}")
        print(f"recorded {out.relative_to(FIXTURES)} ({len(client.plans)} attempts)")


def draft_inputs() -> "DraftInputs":
    """Rohan's Ledgerline email: highlights from the recorded tailor plan, a fictional EM contact."""
    from app.models import Contact
    from app.models.enums import RoleCategory
    from app.schemas.tailor import TailorPlan
    from app.services.email.drafter import DraftInputs
    from app.services.resume.skills import get_lexicon
    from app.services.resume.validator import master_skill_set
    from tests.matching_fixtures import fixture_jobs, fixture_resume, unsaved_job

    job, company = unsaved_job(next(i for i in fixture_jobs() if i["key"] == "relevant"))
    resume = fixture_resume()
    plans = json.loads((FIXTURES / "llm" / "tailor" / "rohan_ledgerline.json").read_text())
    plan = TailorPlan.model_validate(plans[-1])
    texts = {b.id: b.text for b in resume.all_bullets()} | plan.rephrasing_map()
    return DraftInputs(
        job=job,
        company=company,
        contact=Contact(
            full_name="Priya Nair",
            email="priya@ledgerline.example",
            title="Engineering Manager",
            role_category=RoleCategory.ENG_MANAGER,
        ),
        basics=resume.basics,
        about_me="Third-year CS student at a Bengaluru college who enjoys building backend services.",
        highlights=[texts[i] for i in plan.selected_bullet_ids if i in texts][:2],
        skills=master_skill_set(resume, get_lexicon()),
    )


async def record_draft() -> None:
    """Records every attempt (the validator may reject the first) so tests replay the real sequence."""
    from app.schemas.outreach import EmailDraft
    from app.services.email.drafter import Drafter, compose_body, validate_draft

    class Recording(GeminiClient):
        drafts: list[EmailDraft] = []  # noqa: RUF012

        async def generate(self, request, output_type, **kwargs):  # type: ignore[no-untyped-def]
            request = type(request)(**{**request.__dict__, "use_cache": False})
            draft = await super().generate(request, output_type, **kwargs)
            self.drafts.append(draft)
            return draft

    settings = get_settings()
    client = Recording(
        default_api_key=settings.gemini_api_key,
        model_smart=settings.llm_model_smart,
        model_fast=settings.llm_model_fast,
        limiter=RateLimiter(get_redis(), rpm=settings.llm_rpm, rpd=settings.llm_rpd),
    )
    inputs = draft_inputs()
    drafter = Drafter(client)
    try:
        result = await drafter.draft(inputs, None)
        print(result.subject, "\n", result.body, sep="")
    finally:
        out = FIXTURES / "llm" / "draft_email" / "rohan_ledgerline.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([d.model_dump() for d in client.drafts], indent=2) + "\n")
        contexts = drafter.contexts(inputs)
        for i, d in enumerate(client.drafts, 1):
            issues = validate_draft(
                d,
                contexts,
                compose_body(d, inputs.contact, inputs.basics),
                [inputs.job.description_text, *inputs.highlights],
            )
            print(f"attempt {i}: issues={[x.code for x in issues]}")
        print(f"recorded {out.relative_to(FIXTURES)} ({len(client.drafts)} attempts)")


class _Recording(GeminiClient):
    """Keeps every validated output (the validator may reject the first) so tests replay the real
    sequence. Never served from the LLM cache."""

    outputs: list[Any] = []  # noqa: RUF012

    async def generate(self, request, output_type, **kwargs):  # type: ignore[no-untyped-def]
        request = type(request)(**{**request.__dict__, "use_cache": False})
        result = await super().generate(request, output_type, **kwargs)
        self.outputs.append(result)
        return result


def _recording() -> _Recording:
    settings = get_settings()
    _Recording.outputs = []
    return _Recording(
        default_api_key=settings.gemini_api_key,
        model_smart=settings.llm_model_smart,
        model_fast=settings.llm_model_fast,
        limiter=RateLimiter(get_redis(), rpm=settings.llm_rpm, rpd=settings.llm_rpd),
    )


def _open_candidate() -> dict[str, Any]:
    from app.services.matching.profile import candidate_payload
    from tests.matching_fixtures import FIXTURE_PREFS, fixture_resume

    prefs = FIXTURE_PREFS.model_copy(update={"target_roles": ["Backend Intern"]})
    return candidate_payload(prefs, fixture_resume())


async def record_match_company() -> None:
    from app.services.prospects.matching import CompanyScorer, company_payload
    from tests.prospect_fixtures import yc_companies

    companies = yc_companies()
    scored = await CompanyScorer(_client())._request(
        _open_candidate(), [company_payload(c) for c in companies], None
    )
    out = FIXTURES / "llm" / "match_company" / "yc_companies.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([s.model_dump() for s in scored.values()], indent=2) + "\n")
    for c in companies:
        from app.services.prospects.matching import company_ref

        item = scored.get(company_ref(c))
        print(f"{c.name:20} {item.fit_score if item else '-':>4}  {item.angle if item else ''}")
    print(f"recorded {out.relative_to(FIXTURES)} ({len(scored)} of {len(companies)} companies scored)")


def _open_brief() -> tuple[Any, Any]:
    from app.services.resume.tailor import OpenBrief
    from tests.prospect_fixtures import OPEN_DRAFT_DOMAIN, yc_companies

    company = next(c for c in yc_companies() if c.domain == OPEN_DRAFT_DOMAIN)
    scored = json.loads((FIXTURES / "llm" / "match_company" / "yc_companies.json").read_text())
    from app.services.prospects.matching import company_ref

    angle = next(s["angle"] for s in scored if s["company_ref"] == company_ref(company))
    brief = OpenBrief(
        company=company.name, target_roles=["Backend Intern"], about=company.description or "", angle=angle
    )
    return company, brief


async def record_tailor_open() -> None:
    from app.services.resume.skills import get_lexicon
    from app.services.resume.tailor import Tailor
    from app.services.resume.validator import validate_plan
    from tests.matching_fixtures import fixture_resume

    client = _recording()
    _, brief = _open_brief()
    resume = fixture_resume()
    try:
        await Tailor(client).plan_open(resume, brief, None)
    finally:
        out = FIXTURES / "llm" / "tailor_open" / "rohan_abstra.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([p.model_dump() for p in client.outputs], indent=2) + "\n")
        for i, plan in enumerate(client.outputs, 1):
            print(f"attempt {i}: issues={[x.code for x in validate_plan(plan, resume, get_lexicon())]}")
        print(f"recorded {out.relative_to(FIXTURES)} ({len(client.outputs)} attempts)")


def open_draft_inputs() -> "OpenDraftInputs":
    """Rohan's email to Abstra's CTO (fictional contact), highlights from the recorded open plan."""
    from app.models import Contact
    from app.models.enums import RoleCategory
    from app.schemas.tailor import TailorPlan
    from app.services.email.drafter import OpenDraftInputs
    from app.services.resume.skills import get_lexicon
    from app.services.resume.validator import master_skill_set
    from tests.matching_fixtures import fixture_resume

    company, brief = _open_brief()
    resume = fixture_resume()
    plans = json.loads((FIXTURES / "llm" / "tailor_open" / "rohan_abstra.json").read_text())
    plan = TailorPlan.model_validate(plans[-1])
    texts = {b.id: b.text for b in resume.all_bullets()} | plan.rephrasing_map()
    return OpenDraftInputs(
        company=company,
        contact=Contact(
            full_name="Asha Rao",
            email="asha@abstra.example",
            title="Co-founder & CTO",
            role_category=RoleCategory.FOUNDER,
        ),
        basics=resume.basics,
        about_me="Third-year CS student at a Bengaluru college who enjoys building backend services.",
        highlights=[texts[i] for i in plan.selected_bullet_ids if i in texts][:2],
        skills=master_skill_set(resume, get_lexicon()),
        angle=brief.angle,
        target_roles=["Backend Intern"],
        employment_types=["internship"],
    )


async def record_draft_open() -> None:
    from app.services.email.drafter import Drafter, compose_body, opening_claims, validate_draft

    client = _recording()
    inputs = open_draft_inputs()
    drafter = Drafter(client)
    try:
        result = await drafter.draft_open(inputs, None)
        print(result.subject, "\n", result.body, sep="")
    finally:
        out = FIXTURES / "llm" / "draft_open_email" / "rohan_abstra.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([d.model_dump() for d in client.outputs], indent=2) + "\n")
        contexts = drafter.open_contexts(inputs)
        for i, d in enumerate(client.outputs, 1):
            composed = compose_body(d, inputs.contact, inputs.basics)
            issues = validate_draft(d, contexts, composed, [*contexts, *inputs.highlights])
            issues += opening_claims(d.subject, d.body)
            print(f"attempt {i}: issues={[x.code for x in issues]}")
        print(f"recorded {out.relative_to(FIXTURES)} ({len(client.outputs)} attempts)")


async def main() -> None:
    settings = get_settings()
    client = _client()
    prompt = load_prompt("parse_resume")
    RECORDED.mkdir(parents=True, exist_ok=True)
    for filename in FIXTURE_FILES:
        document = extract_document((RESUMES / filename).read_bytes(), filename)
        resume_text, links = build_parse_prompt(document, find_urls(document))
        request = prompt.request(tier="fast", resume_text=resume_text, links=links)
        request = type(request)(**{**request.__dict__, "use_cache": False})
        parsed = await client.generate(request, ParsedResume)
        out = RECORDED / f"{Path(filename).stem}.json"
        out.write_text(parsed.model_dump_json(indent=2) + "\n")
        print(f"recorded {out.relative_to(FIXTURES)} (prompt v{prompt.version}, {settings.llm_model_fast})")


if __name__ == "__main__":
    modes = {
        "hn": record_hn,
        "match": record_match,
        "tailor": record_tailor,
        "draft": record_draft,
        "match_company": record_match_company,
        "tailor_open": record_tailor_open,
        "draft_open": record_draft_open,
    }
    asyncio.run(modes[sys.argv[1]]() if sys.argv[1:] else main())
