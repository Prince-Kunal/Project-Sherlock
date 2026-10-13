"""Workable public widget API (no key):
GET apply.workable.com/api/v1/widget/accounts/{account}?details=true

Returns every published job with its HTML description. Accounts that turned the widget off answer
with an empty list, which the admin "add company" check shows as 0 jobs.
"""

from datetime import UTC, datetime
from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import detect_employment_type, detect_remote, html_to_text

BASE_URL = "https://apply.workable.com/api/v1/widget/accounts"


def _date(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _location(job: dict[str, Any]) -> str | None:
    places = []
    for loc in job.get("locations") or [{"city": job.get("city"), "country": job.get("country")}]:
        if loc.get("hidden"):
            continue
        place = ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
        if place and place not in places:
            places.append(place)
    location = "; ".join(places)
    if job.get("telecommuting"):
        location = f"Remote - {location}" if location else "Remote"
    return location or None


class WorkableSource(JobSource):
    source = JobSourceType.WORKABLE

    def __init__(self, http: PoliteHttpClient) -> None:
        self._http = http

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        if not isinstance(target, CompanyRef) or not target.ats_token:
            raise ValueError("Workable polls a company board")
        return await self._board(target.ats_token, target.name, target.domain)

    async def _board(self, token: str, name: str | None, domain: str | None) -> list[RawJob]:
        data = await self._http.get_json(f"{BASE_URL}/{token}", params={"details": "true"})
        return [
            RawJob(
                source=self.source,
                external_id=job.get("shortcode"),
                payload=job,
                company_name=name or data.get("name") or token,
                company_domain=domain,
            )
            for job in data.get("jobs") or []
            if isinstance(job, dict)
        ]

    async def fetch_job(self, token: str, shortcode: str) -> RawJob:
        """One posting, picked from the board (the widget API has no single-job endpoint)."""
        for raw in await self._board(token, None, None):
            if str(raw.external_id or "").upper() == shortcode.upper():
                return raw
        raise MalformedJobError("that Workable posting isn't on the company's public board")

    def normalize(self, raw: RawJob) -> JobIn:
        job = raw.payload
        title = str(job.get("title") or "").strip()
        if not title:
            raise MalformedJobError("Workable job without a title")
        location = _location(job)
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name or "Unknown",
            company_domain=raw.company_domain,
            title=title,
            location=location,
            remote=detect_remote(location, None, True if job.get("telecommuting") else None),
            employment_type=detect_employment_type(title, job.get("employment_type")),
            description_text=html_to_text(job.get("description")),
            url=job.get("url") or job.get("shortlink"),
            posted_at=_date(job.get("published_on") or job.get("created_at")),
        )
