"""LLM rerank (PLAN.md Phase 3): `prompts/match.md` on the fast model, 10 jobs per request.

A batch response is validated leniently first (each item just needs its `job_ref`), then every item
strictly as `ScoredJob`. Items that are invalid or missing are re-scored one at a time, so one bad
item doesn't cost the whole batch.
"""

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.models import Company, Job
from app.schemas.matches import ScoredJob, ScoredJobLoose
from app.services.llm.client import LLMClient, LLMOutputError
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.matching.profile import JOB_DESCRIPTION_CHARS
from app.services.resume.skills import get_lexicon

log = logging.getLogger(__name__)

_STRICT_SCHEMA = TypeAdapter(list[ScoredJob]).json_schema()
MAX_MISSING = 6


def job_ref(job: Job) -> str:
    """Stable short id for a job inside a prompt. Derived from the dedupe hash (not list position or
    the row id), so recorded responses stay valid however the batch is ordered."""
    return job.dedupe_hash[:8]


def job_payload(job: Job, company: Company) -> dict[str, Any]:
    return {
        "job_ref": job_ref(job),
        "title": job.title,
        "company": company.name,
        "location": job.location,
        "remote": job.remote,
        "employment_type": job.employment_type,
        "description": redact_pii(job.description_text[:JOB_DESCRIPTION_CHARS]),
    }


@dataclass
class BatchOutcome:
    scored: dict[str, ScoredJob] = field(default_factory=dict)  # by job_ref
    unscorable: list[str] = field(default_factory=list)  # refs that failed even on their own


def clean_skills(result: ScoredJob, user_skills: set[str]) -> tuple[list[str], list[str]]:
    """Deterministic guard on the LLM's skill lists: a "matched" skill must be one the user really
    has; a "missing" one must not be. Names are canonicalised and deduplicated."""
    lexicon = get_lexicon()
    matched = [s for s in lexicon.normalize_all(result.matched_skills) if s in user_skills]
    missing = [s for s in lexicon.normalize_all(result.missing_must_haves) if s not in user_skills]
    return matched, missing[:MAX_MISSING]


class Reranker:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._prompt = load_prompt("match")

    async def score_batch(
        self,
        candidate: dict[str, Any],
        jobs: Sequence[tuple[Job, Company]],
        api_key: str | None,
        can_call: Callable[[], bool],
    ) -> BatchOutcome:
        """Score `jobs` in one request, then re-score failed items alone while `can_call()` allows.
        Items left unscored when the budget runs out are in neither `scored` nor `unscorable`."""
        outcome = BatchOutcome()
        payloads = {job_ref(job): job_payload(job, company) for job, company in jobs}
        try:
            outcome.scored = await self.request_scores(candidate, list(payloads.values()), api_key)
        except LLMOutputError as exc:
            log.warning("match batch of %d failed validation twice: %s", len(payloads), exc.errors[:300])
            return outcome  # nothing stored; these jobs are retried on a later run

        for ref in [r for r in payloads if r not in outcome.scored]:
            if not can_call():
                break
            try:
                single = await self.request_scores(candidate, [payloads[ref]], api_key)
            except LLMOutputError:
                single = {}
            if ref in single:
                outcome.scored[ref] = single[ref]
            else:
                outcome.unscorable.append(ref)
        return outcome

    async def request_scores(
        self, candidate: dict[str, Any], jobs: list[dict[str, Any]], api_key: str | None
    ) -> dict[str, ScoredJob]:
        request = self._prompt.request(
            tier="fast",
            api_key=api_key,
            candidate=json.dumps(candidate, ensure_ascii=False),
            jobs=json.dumps(jobs, ensure_ascii=False),
        )
        items = await self._llm.generate(request, list[ScoredJobLoose], response_schema=_STRICT_SCHEMA)
        wanted = {job["job_ref"] for job in jobs}
        scored: dict[str, ScoredJob] = {}
        for item in items:
            if item.job_ref not in wanted or item.job_ref in scored:
                continue
            try:
                scored[item.job_ref] = ScoredJob.model_validate(item.model_dump())
            except ValidationError as exc:
                log.info("match item %s invalid: %s", item.job_ref, exc.errors()[0].get("msg"))
        return scored
