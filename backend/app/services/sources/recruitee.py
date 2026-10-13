"""Recruitee public careers-site API (no key): GET {company}.recruitee.com/api/offers/

Every published offer with HTML description and requirements, locations and an employment-type code
(`fulltime_permanent`, `internship`, ...).
"""

from datetime import UTC, datetime
from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import detect_employment_type, detect_remote, html_to_text


def _date(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    except ValueError:
        return None


def _location(offer: dict[str, Any]) -> str | None:
    places = []
    for loc in offer.get("locations") or []:
        place = ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
        if place and place not in places:
            places.append(place)
    location = "; ".join(places) or offer.get("location") or ""
    if offer.get("remote"):
        location = f"Remote - {location}" if location else "Remote"
    return location or None


class RecruiteeSource(JobSource):
    source = JobSourceType.RECRUITEE

    def __init__(self, http: PoliteHttpClient) -> None:
        self._http = http

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        if not isinstance(target, CompanyRef) or not target.ats_token:
            raise ValueError("Recruitee polls a company board")
        data = await self._http.get_json(f"https://{target.ats_token}.recruitee.com/api/offers/")
        return [
            RawJob(
                source=self.source,
                external_id=str(offer["id"]) if offer.get("id") is not None else None,
                payload=offer,
                company_name=target.name,
                company_domain=target.domain,
            )
            for offer in data.get("offers") or []
            if isinstance(offer, dict) and offer.get("status", "published") == "published"
        ]

    async def fetch_job(self, token: str, slug: str) -> RawJob:
        """One offer by its slug, picked from the board."""
        data = await self._http.get_json(f"https://{token}.recruitee.com/api/offers/")
        for offer in data.get("offers") or []:
            if isinstance(offer, dict) and offer.get("slug") == slug:
                name = offer.get("company_name") or token
                return RawJob(
                    source=self.source, external_id=str(offer.get("id")), payload=offer, company_name=name
                )
        raise MalformedJobError("that Recruitee offer isn't on the company's public board")

    def normalize(self, raw: RawJob) -> JobIn:
        offer = raw.payload
        title = str(offer.get("title") or "").strip()
        if not title:
            raise MalformedJobError("Recruitee offer without a title")
        location = _location(offer)
        description = "\n\n".join(
            t for t in (html_to_text(offer.get("description")), html_to_text(offer.get("requirements"))) if t
        )
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name or "Unknown",
            company_domain=raw.company_domain,
            title=title,
            location=location,
            remote=detect_remote(location, None, True if offer.get("remote") else None),
            employment_type=detect_employment_type(title, offer.get("employment_type_code")),
            description_text=html_to_text(description),
            url=offer.get("careers_url"),
            posted_at=_date(offer.get("published_at") or offer.get("created_at")),
        )
