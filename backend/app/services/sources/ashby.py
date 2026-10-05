"""Ashby job boards: GET api.ashbyhq.com/posting-api/job-board/{name} (`publishedAt` when present)."""

from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.greenhouse import parse_datetime
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import detect_employment_type, detect_remote, html_to_text

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


class AshbySource(JobSource):
    source = JobSourceType.ASHBY

    def __init__(self, http: PoliteHttpClient) -> None:
        self._http = http

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        if not isinstance(target, CompanyRef) or not target.ats_token:
            raise ValueError("Ashby polls a company board")
        jobs = await self._board(target.ats_token)
        return [self._raw(job, target.name, target.domain) for job in jobs]

    async def fetch_job(self, token: str, job_id: str) -> RawJob:
        """Ashby has no public single-posting endpoint; find it on the board."""
        for job in await self._board(token):
            if job.get("id") == job_id:
                return self._raw(job, token, None)
        raise MalformedJobError(f"Ashby posting {job_id} not found on board {token}")

    async def _board(self, token: str) -> list[dict[str, Any]]:
        data = await self._http.get_json(f"{BASE_URL}/{token}")
        return [j for j in data.get("jobs") or [] if isinstance(j, dict) and j.get("isListed", True)]

    def _raw(self, job: dict[str, Any], company: str, domain: str | None) -> RawJob:
        return RawJob(
            source=self.source,
            external_id=job.get("id"),
            payload=job,
            company_name=company,
            company_domain=domain,
        )

    def normalize(self, raw: RawJob) -> JobIn:
        job = raw.payload
        title = str(job.get("title") or "").strip()
        if not title:
            raise MalformedJobError("Ashby job without a title")
        locations = [
            job.get("location"),
            *[(s or {}).get("location") for s in job.get("secondaryLocations") or []],
        ]
        location = " / ".join(dict.fromkeys(loc for loc in locations if loc)) or None
        is_remote = job.get("isRemote")
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name or "Unknown",
            company_domain=raw.company_domain,
            title=title,
            location=location,
            remote=detect_remote(
                location, job.get("workplaceType"), is_remote if isinstance(is_remote, bool) else None
            ),
            employment_type=detect_employment_type(title, job.get("employmentType")),
            description_text=job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml")),
            url=job.get("jobUrl"),
            posted_at=parse_datetime(job.get("publishedAt")),
        )
