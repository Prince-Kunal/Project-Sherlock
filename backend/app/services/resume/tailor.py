"""Resume tailoring for one job (PLAN.md Phase 4).

plan (LLM, smart model) → validate (deterministic; one retry with the issues) → apply → JD spelling →
render to one page → ATS check (invariant 11) → diff. Any failure raises `TailorError` with a reason
the caller stores as the draft's `failure_reason`.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.models import Company, Job
from app.schemas.resume import Bullet, MasterResume
from app.schemas.tailor import ResumeChange, SectionKey, TailorIssue, TailorPlan
from app.services.llm.client import LLMClient
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.resume.assemble import (
    PageOverflowError,
    apply_jd_spelling,
    apply_plan,
    jd_must_haves,
    render_one_page,
    resume_diff,
)
from app.services.resume.ats_check import AtsExpectations, AtsReport, KeywordCoverage, ats_check
from app.services.resume.render import RenderedResume, resume_filename
from app.services.resume.skills import SkillLexicon, get_lexicon
from app.services.resume.validator import validate_plan

log = logging.getLogger(__name__)

JD_CHARS = 4000


class TailorError(Exception):
    """Tailoring failed; `reason` is stored as failure_reason (validation_failed, page_overflow,
    ats_check_failed)."""

    def __init__(
        self, reason: str, message: str, issues: list[TailorIssue] | None = None, ats: AtsReport | None = None
    ) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.issues = issues or []
        self.ats = ats


@dataclass
class TailorResult:
    plan: TailorPlan
    resume: MasterResume
    section_order: list[SectionKey]
    rendered: RenderedResume
    ats: AtsReport
    keyword_coverage: KeywordCoverage
    diff: list[ResumeChange]
    swaps: dict[str, str]  # canonical skill → JD spelling used
    dropped_to_fit: list[str]

    @property
    def filename(self) -> str:
        return resume_filename(self.resume.basics.name)


def _bullets(bullets: list[Bullet]) -> list[dict[str, Any]]:
    return [{"id": b.id, "text": redact_pii(b.text), "skills": b.skills, "pinned": b.pinned} for b in bullets]


def resume_for_prompt(master: MasterResume) -> dict[str, Any]:
    """The master resume with ids, as the tailor prompt sees it: no basics (PLAN.md §3.1)."""
    return {
        "summary": redact_pii(master.summary) if master.summary else None,
        "education": [
            {
                "institution": e.institution,
                "degree": " in ".join(x for x in (e.degree, e.field) if x) or None,
                "end": e.end,
                "bullets": _bullets(e.bullets),
            }
            for e in master.education
        ],
        "experience": [
            {"role": e.role, "org": e.org, "start": e.start, "end": e.end, "bullets": _bullets(e.bullets)}
            for e in master.experience
        ],
        "projects": [
            {"name": p.name, "tech": p.tech, "bullets": _bullets(p.bullets)} for p in master.projects
        ],
        "achievements": _bullets(master.achievements),
        "skills": master.skills,
    }


def job_for_prompt(job: Job, company: Company) -> dict[str, Any]:
    return {
        "title": job.title,
        "company": company.name,
        "location": job.location,
        "description": redact_pii(job.description_text[:JD_CHARS]),
    }


def _feedback(issues: list[TailorIssue], previous: TailorPlan) -> str:
    lines = [f"- [{i.code}] {i.bullet_id + ': ' if i.bullet_id else ''}{i.message}" for i in issues]
    return "\n".join(lines) + "\n\nYour previous plan:\n```json\n" + previous.model_dump_json() + "\n```"


class Tailor:
    def __init__(self, llm: LLMClient, lexicon: SkillLexicon | None = None) -> None:
        self._llm = llm
        self._lexicon = lexicon or get_lexicon()
        self._prompt = load_prompt("tailor")

    async def plan(self, master: MasterResume, job: Job, company: Company, api_key: str | None) -> TailorPlan:
        """A plan that passes the validator, with one retry carrying the issues found."""
        variables = {
            "job": json.dumps(job_for_prompt(job, company), ensure_ascii=False),
            "resume": json.dumps(resume_for_prompt(master), ensure_ascii=False),
        }
        feedback = "(none)"
        issues: list[TailorIssue] = []
        for attempt in (1, 2):
            request = self._prompt.request(
                tier="smart", api_key=api_key, allow_fallback=True, feedback=feedback, **variables
            )
            plan = await self._llm.generate(request, TailorPlan)
            issues = validate_plan(plan, master, self._lexicon)
            if not issues:
                return plan
            log.info("tailor plan attempt %d rejected: %s", attempt, [i.code for i in issues])
            feedback = _feedback(issues, plan)
        raise TailorError("validation_failed", "the plan failed validation twice", issues=issues)

    async def tailor(
        self, master: MasterResume, job: Job, company: Company, api_key: str | None
    ) -> TailorResult:
        plan = await self.plan(master, job, company, api_key)
        return await self.build(master, plan, job.description_text)

    async def build(self, master: MasterResume, plan: TailorPlan, jd_text: str) -> TailorResult:
        """Everything after the LLM: deterministic, so it's tested directly with hand-written plans."""
        issues = validate_plan(plan, master, self._lexicon)
        if issues:  # callers normally pass a validated plan; never render an unchecked one
            raise TailorError("validation_failed", "plan failed validation", issues=issues)
        draft = apply_plan(master, plan, self._lexicon)
        must_haves = jd_must_haves(jd_text, plan.jd_keywords, self._lexicon)
        swaps = apply_jd_spelling(draft, must_haves, master, self._lexicon)
        try:
            rendered, dropped = await render_one_page(draft)
        except PageOverflowError as exc:
            raise TailorError("page_overflow", str(exc)) from exc

        report = await ats_check(rendered.pdf, AtsExpectations.from_rendered(rendered, must_haves))
        if not report.passed:
            # Invariant 11: re-render once, then give up rather than attach a failing PDF.
            rendered, more = await render_one_page(draft)
            dropped += more
            report = await ats_check(rendered.pdf, AtsExpectations.from_rendered(rendered, must_haves))
            if not report.passed:
                raise TailorError("ats_check_failed", "; ".join(report.failures), ats=report)

        coverage = report.keyword_coverage or KeywordCoverage(score=1.0, matched=[], missing=[])
        return TailorResult(
            plan=plan,
            resume=draft.resume,
            section_order=draft.section_order,
            rendered=rendered,
            ats=report,
            keyword_coverage=coverage,
            diff=resume_diff(master, draft.resume),
            swaps=swaps,
            dropped_to_fit=dropped,
        )
