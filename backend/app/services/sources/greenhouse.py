"""Greenhouse job boards: GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true.

posted_at uses `first_published` (the API added it; PLAN.md assumed no creation date, deviation agreed
2026-10-05), falling back to first_seen_at. `updated_at` is informational only.
"""

from datetime import datetime
from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import detect_employment_type, detect_remote, html_to_text

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _metadata_value(job: dict[str, Any], *names: str) -> str | None:
    for item in job.get("metadata") or []:
        name = str(item.get("name") or "").lower()
        if any(n in name for n in names) and isinstance(item.get("value"), str):
            return str(item["value"])
    return None


class GreenhouseSource(JobSource):
    source = JobSourceType.GREENHOUSE

    def __init__(self, http: PoliteHttpClient) -> None:
        self._http = http

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        if not isinstance(target, CompanyRef) or not target.ats_token:
            raise ValueError("Greenhouse polls a company board")
        data = await self._http.get_json(f"{BASE_URL}/{target.ats_token}/jobs", params={"content": "true"})
        return [self._raw(job, target.name, target.domain) for job in data.get("jobs") or []]

    async def fetch_job(self, token: str, job_id: str) -> RawJob:
        job = await self._http.get_json(f"{BASE_URL}/{token}/jobs/{job_id}")
        return self._raw(job, job.get("company_name") or token, None)

    def _raw(self, job: dict[str, Any], company: str, domain: str | None) -> RawJob:
        return RawJob(
            source=self.source,
            external_id=str(job["id"]) if job.get("id") is not None else None,
            payload=job,
            company_name=company,
            company_domain=domain,
        )

    def normalize(self, raw: RawJob) -> JobIn:
        job = raw.payload
        title = str(job.get("title") or "").strip()
        if not title:
            raise MalformedJobError("Greenhouse job without a title")
        location = (job.get("location") or {}).get("name")
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name or job.get("company_name") or "Unknown",
            company_domain=raw.company_domain,
            title=title,
            location=location,
            remote=detect_remote(location, _metadata_value(job, "workplace", "remote")),
            employment_type=detect_employment_type(title, _metadata_value(job, "employment", "commitment")),
            description_text=html_to_text(job.get("content")),
            url=job.get("absolute_url"),
            posted_at=parse_datetime(job.get("first_published")),
        )
