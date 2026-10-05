"""HN "Ask HN: Who is hiring?" via the Algolia HN API; comments parsed by the fast LLM model.

Free-tier quota (~18 requests/day/model) can't cover a whole thread (200-500 comments), so:
comments are prefiltered by keywords (locations/roles our users care about), parsed 10 per request,
at most `max_requests_per_run` requests per poll, and processed comment ids are remembered in Redis,
so later polls continue where the last one stopped. Uses the owner's key (shared work, PLAN.md §3.1).
"""

import json
import logging
import re
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.models.enums import JobSourceType
from app.services.llm.client import LLMClient, LLMError, LLMQuotaExhaustedError
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.greenhouse import parse_datetime
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import company_domain_from_url, html_to_text

log = logging.getLogger(__name__)

ALGOLIA = "https://hn.algolia.com/api/v1"
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PROCESSED_TTL_SECONDS = 45 * 24 * 3600
# Hosts that are job boards or HN itself, not the hiring company's own site.
DEFAULT_KEYWORDS = ["remote", "india", "bengaluru", "bangalore", "anywhere", "worldwide", "global", "intern"]


class HNJob(BaseModel):
    comment_id: int
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str | None = None
    remote: bool | None = None
    employment_type: Literal["internship", "full_time", "part_time", "contract"] | None = None
    url: str | None = None


class HNSource(JobSource):
    source = JobSourceType.HN

    def __init__(
        self,
        http: PoliteHttpClient,
        llm: LLMClient,
        redis: Redis,
        *,
        keywords: list[str] | None = None,
        max_requests_per_run: int = 2,
        batch_size: int = 10,
    ) -> None:
        self._http = http
        self._llm = llm
        self._redis = redis
        self._keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS) if k.strip()]
        self._max_requests = max_requests_per_run
        self._batch_size = batch_size

    async def latest_thread_id(self) -> str | None:
        data = await self._http.get_json(
            f"{ALGOLIA}/search_by_date", params={"tags": "story,author_whoishiring", "hitsPerPage": 6}
        )
        for hit in data.get("hits") or []:
            if "who is hiring" in str(hit.get("title") or "").lower():
                return str(hit["objectID"])
        return None

    def _relevant(self, text: str) -> bool:
        lowered = text.lower()
        return any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in self._keywords)

    async def fetch(self, target: CompanyRef | JobQuery | None = None) -> list[RawJob]:
        thread_id = await self.latest_thread_id()
        if thread_id is None:
            return []
        thread = await self._http.get_json(f"{ALGOLIA}/items/{thread_id}")
        processed_key = f"hn:processed:{thread_id}"
        members = await cast(Awaitable[set[str]], self._redis.smembers(processed_key))
        processed = {int(x) for x in members}

        pending = []
        for comment in thread.get("children") or []:
            text = html_to_text(comment.get("text"))
            if comment.get("id") in processed or not text or comment.get("type") != "comment":
                continue
            if self._relevant(text):
                pending.append({**comment, "plain": text})

        raws: list[RawJob] = []
        prompt = load_prompt("parse_hn_comment")
        for start in range(0, min(len(pending), self._max_requests * self._batch_size), self._batch_size):
            batch = pending[start : start + self._batch_size]
            emails = {c["id"]: sorted({e.lower() for e in _EMAIL_RE.findall(c["plain"])}) for c in batch}
            comments = [{"comment_id": c["id"], "text": redact_pii(c["plain"])[:4000]} for c in batch]
            try:
                jobs = await self._llm.generate(
                    prompt.request(tier="fast", comments=json.dumps(comments, ensure_ascii=False)),
                    list[HNJob],
                )
            except LLMQuotaExhaustedError:
                log.warning(
                    "hn: LLM daily quota exhausted; %d comments left for later polls", len(pending) - start
                )
                break
            except LLMError:
                log.exception("hn: could not parse a batch of %d comments; skipping it", len(batch))
                jobs = []
            await cast(Awaitable[int], self._redis.sadd(processed_key, *[str(c["id"]) for c in batch]))
            await self._redis.expire(processed_key, _PROCESSED_TTL_SECONDS)
            by_id = {c["id"]: c for c in batch}
            for job in jobs:
                comment = by_id.get(job.comment_id)
                if comment is None:
                    continue  # the model referenced a comment it wasn't given
                raws.append(
                    RawJob(
                        source=self.source,
                        external_id=f"{job.comment_id}:{job.title}"[:255],
                        payload={
                            "job": job.model_dump(),
                            "created_at": comment.get("created_at"),
                            "text": comment["plain"],
                            "author": comment.get("author"),
                            "contact_emails": emails.get(job.comment_id, []),
                        },
                        company_name=job.company,
                        company_domain=company_domain_from_url(job.url),
                    )
                )
        return raws

    def normalize(self, raw: RawJob) -> JobIn:
        payload: dict[str, Any] = raw.payload
        job = HNJob.model_validate(payload.get("job") or {})
        if not raw.company_name:
            raise MalformedJobError("HN job without a company")
        comment_url = f"https://news.ycombinator.com/item?id={job.comment_id}"
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name,
            company_domain=raw.company_domain,
            title=job.title,
            location=job.location,
            remote=job.remote,
            employment_type=job.employment_type,
            description_text=html_to_text(payload.get("text")),
            url=job.url or comment_url,
            posted_at=parse_datetime(payload.get("created_at")) or datetime.now(UTC),
            source_meta={
                "hn_comment_id": job.comment_id,
                "hn_comment_url": comment_url,
                "hn_author": payload.get("author"),
                "contact_emails": payload.get("contact_emails") or [],
            },
        )
