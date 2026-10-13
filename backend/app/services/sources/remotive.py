"""Remotive public API (no key): GET remotive.com/api/remote-jobs

Remote jobs from many companies, so it's ingested like an aggregator. Remotive's terms: link back to
the Remotive posting and name Remotive as the source (the job's `url` is the Remotive page and
`source_meta.attribution` says "Remotive"), and request it no more than ~4 times a day (poll_sources
runs every 6 hours, and only when some user has the Remotive feed switched on). Listings are delayed
by 24 hours on Remotive's side.
"""

from datetime import UTC, datetime
from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import detect_employment_type, html_to_text

API_URL = "https://remotive.com/api/remote-jobs"
CATEGORIES = ("software-dev", "data", "devops", "qa", "product")


def _date(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class RemotiveSource(JobSource):
    source = JobSourceType.REMOTIVE

    def __init__(self, http: PoliteHttpClient, categories: tuple[str, ...] = CATEGORIES) -> None:
        self._http = http
        self._categories = categories

    async def fetch(self, target: CompanyRef | JobQuery | None = None) -> list[RawJob]:
        raws: list[RawJob] = []
        seen: set[str] = set()
        for category in self._categories:
            data = await self._http.get_json(API_URL, params={"category": category})
            for job in data.get("jobs") or []:
                if not isinstance(job, dict) or str(job.get("id")) in seen:
                    continue
                seen.add(str(job.get("id")))
                raws.append(
                    RawJob(
                        source=self.source,
                        external_id=str(job["id"]) if job.get("id") is not None else None,
                        payload=job,
                        company_name=str(job.get("company_name") or "").strip() or None,
                    )
                )
        return raws

    def normalize(self, raw: RawJob) -> JobIn:
        job = raw.payload
        title = html_to_text(str(job.get("title") or ""))
        if not title:
            raise MalformedJobError("Remotive job without a title")
        if not raw.company_name:
            raise MalformedJobError("Remotive job without a company")
        region = str(job.get("candidate_required_location") or "").strip()
        location = f"Remote - {region}" if region else "Remote"
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name,
            title=title,
            location=location,
            remote=True,
            employment_type=detect_employment_type(title, job.get("job_type")),
            description_text=html_to_text(job.get("description")),
            url=job.get("url"),
            posted_at=_date(job.get("publication_date")),
            source_meta={"attribution": "Remotive", "category": job.get("category")},
        )
