"""Company matching for open outreach (PLAN.md Phase 8, §8 `match_companies_for_users`):

hard filters (target industries/locations/sizes, the target's excludes, blocked companies, companies
this user emailed in the last 90 days or has an active outreach with) → embedding similarity between
the user's profile and the company → `prompts/match_company.md` on the fast model → company_matches.

Incremental like job matching: a (user, company) pair is scored once. Scoring uses the user's own key
under its own daily allowance (`COMPANY_MATCH_DAILY_LLM_CALLS`); companies not reached wait for the
next run. A target's included companies skip the industry/location/size filters and go first.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import log_context
from app.models import Company, CompanyMatch, Outreach, ProspectTarget, User, UserCompanyBlock
from app.models.enums import INACTIVE_OUTREACH_STATUSES, CompanyMatchStatus
from app.schemas.prospects import ScoredCompany, ScoredCompanyLoose
from app.schemas.resume import MasterResume
from app.services.embeddings.embedder import Embedder
from app.services.llm.client import (
    LLMAuthError,
    LLMClient,
    LLMConfigError,
    LLMOutputError,
    LLMQuotaExhaustedError,
    LLMRateLimitedError,
    metered,
)
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.llm.user_keys import LLMKeyRequiredError, resolve_api_key
from app.services.matching.embed import user_embedding
from app.services.matching.pipeline import daily_window_start, load_preferences
from app.services.matching.profile import candidate_payload, profile_text
from app.services.prospects.discovery import active_targets, company_fits
from app.services.quotas import over_quota
from app.services.resume import store
from app.services.usage import llm_calls_since, record_llm_usage

log = logging.getLogger(__name__)

OPERATION = "match_companies"
RECENTLY_CONTACTED_DAYS = 90
UNSCORABLE_REASON = "Sherlock couldn't score this company automatically."
DESCRIPTION_CHARS = 800
WEBSITE_CHARS = 1200
_STRICT_SCHEMA = TypeAdapter(list[ScoredCompany]).json_schema()


def company_ref(company: Company) -> str:
    """Stable short id inside a prompt (from the domain, not the row id, so recorded responses
    replay in tests whatever ids the rows get)."""
    return hashlib.sha256((company.domain or company.name).lower().encode()).hexdigest()[:8]


def company_payload(company: Company) -> dict[str, Any]:
    return {
        "company_ref": company_ref(company),
        "name": company.name,
        "industry": company.industry,
        "tags": (company.industry_tags or [])[:10],
        "locations": (company.locations or [])[:5],
        "size": company.size_hint.value,
        "employees": company.employee_count,
        "description": redact_pii((company.description or "")[:DESCRIPTION_CHARS]) or None,
        "website": redact_pii((company.website_text or "")[:WEBSITE_CHARS]) or None,
    }


def target_roles(targets: Sequence[ProspectTarget], fallback: list[str]) -> list[str]:
    roles: list[str] = []
    for role in [r for t in targets for r in t.target_roles] or fallback:
        if role not in roles:
            roles.append(role)
    return roles


@dataclass
class CompanyMatchSummary:
    candidates: int = 0
    scored: int = 0
    unscorable: int = 0
    llm_calls: int = 0
    stopped: str | None = None


@dataclass
class CompanyMatchRun:
    users: int = 0
    scored: int = 0
    llm_calls: int = 0
    stopped: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        return {
            "users": self.users,
            "scored": self.scored,
            "llm_calls": self.llm_calls,
            "stopped": len(self.stopped),
        }


class CompanyScorer:
    """One match_company.md request per batch; items missing or invalid in the batch answer are
    re-scored alone while the allowance lasts, and stored as unscorable if that fails too."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._prompt = load_prompt("match_company")

    async def score(
        self,
        candidate: dict[str, Any],
        companies: Sequence[Company],
        api_key: str | None,
        can_call: Callable[[], bool],
    ) -> tuple[dict[str, ScoredCompany], list[str]]:
        payloads = {company_ref(c): company_payload(c) for c in companies}
        try:
            scored = await self._request(candidate, list(payloads.values()), api_key)
        except LLMOutputError as exc:
            log.warning("company batch of %d failed validation twice: %s", len(payloads), exc.errors[:300])
            return {}, []
        unscorable = []
        for ref in [r for r in payloads if r not in scored]:
            if not can_call():
                break
            try:
                single = await self._request(candidate, [payloads[ref]], api_key)
            except LLMOutputError:
                single = {}
            if ref in single:
                scored[ref] = single[ref]
            else:
                unscorable.append(ref)
        return scored, unscorable

    async def _request(
        self, candidate: dict[str, Any], companies: list[dict[str, Any]], api_key: str | None
    ) -> dict[str, ScoredCompany]:
        request = self._prompt.request(
            tier="fast",
            api_key=api_key,
            candidate=json.dumps(candidate, ensure_ascii=False),
            companies=json.dumps(companies, ensure_ascii=False),
        )
        items = await self._llm.generate(request, list[ScoredCompanyLoose], response_schema=_STRICT_SCHEMA)
        wanted = {c["company_ref"] for c in companies}
        scored: dict[str, ScoredCompany] = {}
        for item in items:
            if item.company_ref not in wanted or item.company_ref in scored:
                continue
            try:
                scored[item.company_ref] = ScoredCompany.model_validate(item.model_dump())
            except ValidationError as exc:
                log.info("company item %s invalid: %s", item.company_ref, exc.errors()[0].get("msg"))
        return scored


class CompanyMatcher:
    def __init__(self, *, llm: LLMClient, embedder: Embedder, redis: Redis, settings: Settings) -> None:
        self._embedder = embedder
        self._redis = redis
        self._settings = settings
        self._scorer = CompanyScorer(llm)

    async def candidates(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        targets: list[ProspectTarget],
        vector: list[float],
        now: datetime,
        limit: int,
    ) -> list[tuple[Company, ProspectTarget, float]]:
        """Unscored companies fitting a target, included ones first, then by similarity."""
        blocked = select(UserCompanyBlock.company_id).where(UserCompanyBlock.user_id == user_id)
        busy = select(Outreach.company_id).where(
            Outreach.user_id == user_id,
            or_(
                Outreach.status.not_in(INACTIVE_OUTREACH_STATUSES),
                Outreach.sent_at >= now - timedelta(days=RECENTLY_CONTACTED_DAYS),
            ),
        )
        scored = select(CompanyMatch.company_id).where(CompanyMatch.user_id == user_id)
        distance = Company.embedding.cosine_distance(vector)
        min_sim = self._settings.company_min_sim
        similar = [distance <= 1 - min_sim] if min_sim > 0 else []  # 0: rank only, no threshold
        rows = (
            await session.execute(
                select(Company, (1 - distance).label("similarity"))
                .where(
                    Company.domain.is_not(None),
                    Company.embedding.is_not(None),
                    Company.id.not_in(blocked),
                    Company.id.not_in(busy),
                    Company.id.not_in(scored),
                    *similar,
                )
                .order_by(distance, Company.id)
            )
        ).all()
        included: list[tuple[Company, ProspectTarget, float]] = []
        fitting: list[tuple[Company, ProspectTarget, float]] = []
        for company, similarity in rows:
            for target in targets:
                if company.id in target.exclude_companies:
                    continue
                if company.id in target.include_companies:
                    included.append((company, target, float(similarity)))
                    break
                if company_fits(company, target):
                    fitting.append((company, target, float(similarity)))
                    break
        return (included + fitting)[:limit]

    async def match_user(
        self, session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
    ) -> CompanyMatchSummary:
        now = now or datetime.now(UTC)
        summary = CompanyMatchSummary()
        targets = await active_targets(session, user_id)
        if not targets:
            summary.stopped = "no_targets"
            return summary
        resume_row = await store.get_current(session, user_id)
        if resume_row is None:
            summary.stopped = "no_resume"
            return summary
        prefs = await load_preferences(session, user_id)
        resume = MasterResume.model_validate(resume_row.data)
        roles = target_roles(targets, list(prefs.target_roles))
        vector = await user_embedding(
            self._redis, self._embedder, user_id, resume_row.version, profile_text(roles, resume)
        )
        found = await self.candidates(
            session, user_id, targets, vector, now, self._settings.company_candidates_per_run
        )
        summary.candidates = len(found)
        if not found:
            return summary
        if await over_quota(session, user_id, now):
            summary.stopped = "quota_exceeded"
            return summary
        try:
            api_key = await resolve_api_key(session, user_id)
        except LLMKeyRequiredError:
            summary.stopped = "no_llm_key"
            return summary

        candidate = candidate_payload(prefs.model_copy(update={"target_roles": roles}), resume)
        used = await llm_calls_since(session, user_id, OPERATION, daily_window_start(now))
        allowance = self._settings.company_match_daily_llm_calls - used
        size = self._settings.company_match_batch_size
        with metered() as meter:
            for start in range(0, len(found), size):
                if meter.calls >= allowance:
                    summary.stopped = summary.stopped or "daily_allowance"
                    break
                batch = found[start : start + size]
                before = meter.calls
                try:
                    scored, unscorable = await self._scorer.score(
                        candidate, [c for c, _, _ in batch], api_key, can_call=lambda: meter.calls < allowance
                    )
                except (LLMQuotaExhaustedError, LLMRateLimitedError, LLMAuthError, LLMConfigError) as exc:
                    summary.stopped = type(exc).__name__
                    scored, unscorable = {}, []
                    await record_llm_usage(session, user_id, OPERATION, meter.calls - before)
                    await session.commit()
                    break
                await record_llm_usage(session, user_id, OPERATION, meter.calls - before)
                by_ref = {company_ref(c): (c, t, s) for c, t, s in batch}
                for ref, result in scored.items():
                    company, target, similarity = by_ref[ref]
                    await _save(
                        session, user_id, company.id, target.id, similarity,
                        result.fit_score, result.angle, result.reasoning,
                    )  # fmt: skip
                for ref in unscorable:
                    company, target, similarity = by_ref[ref]
                    await _save(session, user_id, company.id, target.id, similarity, 0, "", UNSCORABLE_REASON)
                summary.scored += len(scored)
                summary.unscorable += len(unscorable)
                await session.commit()
            summary.llm_calls = meter.calls
        return summary

    async def match_all(self, sessions: async_sessionmaker[AsyncSession]) -> CompanyMatchRun:
        run = CompanyMatchRun()
        async with sessions() as session:
            user_ids = list(
                (
                    await session.scalars(
                        select(User.id)
                        .where(User.is_active.is_(True))
                        .where(
                            User.id.in_(
                                select(ProspectTarget.user_id).where(ProspectTarget.is_active.is_(True))
                            )
                        )
                        .order_by(User.created_at)
                    )
                ).all()
            )
        for user_id in user_ids:
            with log_context(user_id=user_id):
                async with sessions() as session:
                    try:
                        summary = await self.match_user(session, user_id)
                    except Exception:
                        log.exception("company matching failed for user %s", user_id)
                        run.stopped[str(user_id)] = "error"
                        continue
                run.users += 1
                run.scored += summary.scored
                run.llm_calls += summary.llm_calls
                if summary.stopped:
                    run.stopped[str(user_id)] = summary.stopped
                log.info("matched companies for user %s: %s", user_id, summary)
        return run


async def _save(
    session: AsyncSession,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    target_id: uuid.UUID,
    similarity: float,
    score: int,
    angle: str,
    reasoning: str,
) -> None:
    await session.execute(
        insert(CompanyMatch)
        .values(
            user_id=user_id,
            company_id=company_id,
            prospect_target_id=target_id,
            embedding_score=similarity,
            score=score,
            angle=angle,
            reasoning=reasoning,
            status=CompanyMatchStatus.NEW,
        )
        .on_conflict_do_nothing(constraint="uq_company_matches_user_company")
    )
