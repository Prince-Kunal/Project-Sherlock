"""Lever postings: GET api.lever.co/v0/postings/{company}?mode=json (`createdAt` is epoch ms)."""

from datetime import UTC, datetime
from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import detect_employment_type, detect_remote, html_to_text

BASE_URL = "https://api.lever.co/v0/postings"


def _from_ms(value: Any) -> datetime | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, UTC)


def _description(job: dict[str, Any]) -> str:
    parts = [
        job.get("openingPlain") or html_to_text(job.get("opening")),
        job.get("descriptionBodyPlain")
        or job.get("descriptionPlain")
        or html_to_text(job.get("descriptionBody") or job.get("description")),
    ]
    for section in job.get("lists") or []:
        parts.append("\n".join(filter(None, [section.get("text"), html_to_text(section.get("content"))])))
    parts.append(job.get("additionalPlain") or html_to_text(job.get("additional")))
    return html_to_text("\n\n".join(p.strip() for p in parts if p and p.strip()))


class LeverSource(JobSource):
    source = JobSourceType.LEVER

    def __init__(self, http: PoliteHttpClient) -> None:
        self._http = http

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        if not isinstance(target, CompanyRef) or not target.ats_token:
            raise ValueError("Lever polls a company board")
        data = await self._http.get_json(f"{BASE_URL}/{target.ats_token}", params={"mode": "json"})
        return [self._raw(job, target.name, target.domain) for job in data if isinstance(job, dict)]

    async def fetch_job(self, token: str, posting_id: str) -> RawJob:
        job = await self._http.get_json(f"{BASE_URL}/{token}/{posting_id}", params={"mode": "json"})
        return self._raw(job, token, None)

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
        title = str(job.get("text") or "").strip()
        if not title:
            raise MalformedJobError("Lever posting without a title")
        categories = job.get("categories") or {}
        location = categories.get("location") or ", ".join(categories.get("allLocations") or []) or None
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name or "Unknown",
            company_domain=raw.company_domain,
            title=title,
            location=location,
            remote=detect_remote(location, job.get("workplaceType")),
            employment_type=detect_employment_type(title, categories.get("commitment")),
            description_text=_description(job),
            url=job.get("hostedUrl"),
            posted_at=_from_ms(job.get("createdAt")),
        )
