"""SmartRecruiters public Posting API (no key):
GET api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=…  (no descriptions)
GET api.smartrecruiters.com/v1/companies/{company}/postings/{id}              (jobAd sections)

Big employers list thousands of postings, so a poll reads at most `max_pages` pages, keeps postings
released in the last `max_age_days`, and fetches details only for ones not stored yet (`known_ids`),
at most `max_details` per poll. Known postings keep their stored description (ingest only replaces a
description with a non-empty one).
"""

import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.greenhouse import parse_datetime
from app.services.sources.http import PoliteHttpClient, SourceHTTPError
from app.services.sources.text import detect_employment_type, detect_remote, html_to_text

BASE_URL = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100
_SECTIONS = ("jobDescription", "qualifications", "additionalInformation", "companyDescription")


def _location(loc: dict[str, Any]) -> str | None:
    parts = [p.strip() for p in str(loc.get("fullLocation") or "").split(",") if p.strip()]
    return ", ".join(parts) or None


def _description(job_ad: dict[str, Any] | None) -> str:
    sections = (job_ad or {}).get("sections") or {}
    parts = []
    for name in _SECTIONS:
        section = sections.get(name) or {}
        text = html_to_text(section.get("text"))
        if text:
            parts.append(f"{section.get('title') or ''}\n{text}".strip())
    return html_to_text("\n\n".join(parts))


class SmartRecruitersSource(JobSource):
    source = JobSourceType.SMARTRECRUITERS

    def __init__(
        self,
        http: PoliteHttpClient,
        *,
        max_pages: int = 5,
        max_age_days: int = 30,
        max_details: int = 40,
        now: datetime | None = None,
    ) -> None:
        self._http = http
        self._max_pages = max_pages
        self._max_age = timedelta(days=max_age_days)
        self._max_details = max_details
        self._now = now

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        if not isinstance(target, CompanyRef) or not target.ats_token:
            raise ValueError("SmartRecruiters polls a company board")
        cutoff = (self._now or datetime.now(UTC)) - self._max_age
        postings: list[dict[str, Any]] = []
        for page in range(self._max_pages):
            data = await self._http.get_json(
                f"{BASE_URL}/{target.ats_token}/postings",
                params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
            )
            content = [p for p in data.get("content") or [] if isinstance(p, dict)]
            postings += content
            if len(content) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= int(data.get("totalFound") or 0):
                break
        recent = [p for p in postings if (parse_datetime(p.get("releasedDate")) or cutoff) >= cutoff]
        raws = []
        details_left = self._max_details
        for posting in recent:
            posting_id = str(posting.get("id") or "")
            if posting_id and posting_id not in target.known_ids and details_left > 0:
                details_left -= 1
                # On failure it's stored without a description and the next poll tries again.
                with contextlib.suppress(SourceHTTPError):
                    posting = await self._http.get_json(
                        f"{BASE_URL}/{target.ats_token}/postings/{posting_id}"
                    )
            raws.append(
                RawJob(
                    source=self.source,
                    external_id=posting_id or None,
                    payload=posting,
                    company_name=target.name,
                    company_domain=target.domain,
                )
            )
        return raws

    async def fetch_job(self, token: str, posting_id: str) -> RawJob:
        job = await self._http.get_json(f"{BASE_URL}/{token}/postings/{posting_id}")
        name = (job.get("company") or {}).get("name") or token
        return RawJob(
            source=self.source, external_id=str(job.get("id") or posting_id), payload=job, company_name=name
        )

    def normalize(self, raw: RawJob) -> JobIn:
        job = raw.payload
        title = str(job.get("name") or "").strip()
        if not title:
            raise MalformedJobError("SmartRecruiters posting without a title")
        loc = job.get("location") or {}
        location = _location(loc)
        company = (job.get("company") or {}).get("identifier") or ""
        url = job.get("postingUrl") or (
            f"https://jobs.smartrecruiters.com/{company}/{raw.external_id}"
            if company and raw.external_id
            else None
        )
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name or "Unknown",
            company_domain=raw.company_domain,
            title=title,
            location=location,
            remote=detect_remote(location, None, True if loc.get("remote") else None),
            employment_type=detect_employment_type(title, (job.get("typeOfEmployment") or {}).get("label")),
            description_text=_description(job.get("jobAd")),
            url=url,
            posted_at=parse_datetime(job.get("releasedDate")),
        )
