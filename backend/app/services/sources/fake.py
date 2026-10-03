from datetime import UTC, datetime, timedelta

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, RawJob

_POSTINGS = [
    ("fake-1", "Backend Engineering Intern", "Bengaluru, India", "internship", 2),
    ("fake-2", "Software Engineer, Platform", "Remote - India", "full_time", 5),
    ("fake-3", "Senior Product Designer", "San Francisco, CA", "full_time", 30),
]


class FakeJobSource(JobSource):
    """Three fixed postings per company (one intern, one full-time, one stale non-engineering role)."""

    source = JobSourceType.GREENHOUSE

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime.now(UTC)

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        company = target.name if isinstance(target, CompanyRef) else "Fake Aggregated Co"
        domain = target.domain if isinstance(target, CompanyRef) else None
        return [
            RawJob(
                source=self.source,
                external_id=f"{company}:{external_id}",
                company_name=company,
                payload={
                    "title": title,
                    "location": location,
                    "employment_type": employment_type,
                    "posted_at": (self._now - timedelta(days=age_days)).isoformat(),
                    "domain": domain,
                    "url": f"https://jobs.example.com/{external_id}",
                    "content": f"<p>{title} at {company}. Python, PostgreSQL, React.</p>",
                },
            )
            for external_id, title, location, employment_type, age_days in _POSTINGS
        ]

    def normalize(self, raw: RawJob) -> JobIn:
        p = raw.payload
        return JobIn(
            source=raw.source,
            external_id=raw.external_id,
            company_name=raw.company_name or "Unknown",
            company_domain=p.get("domain"),
            title=p["title"],
            location=p.get("location"),
            remote="remote" in (p.get("location") or "").lower(),
            employment_type=p.get("employment_type"),
            description_text=p.get("content", ""),
            url=p.get("url"),
            posted_at=datetime.fromisoformat(p["posted_at"]),
        )
