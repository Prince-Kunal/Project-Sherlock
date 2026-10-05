"""Adzuna (India): GET api.adzuna.com/v1/api/jobs/in/search/{page}?app_id&app_key&what&max_days_old.

Queries come from users' target roles. Companies are created on the fly by name (domain unknown
until Phase 5). Adzuna returns only a description snippet.
"""

import re
from typing import Any

from app.models.enums import JobSourceType
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.greenhouse import parse_datetime
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import detect_employment_type, detect_remote, html_to_text

BASE_URL = "https://api.adzuna.com/v1/api/jobs/in/search"
RESULTS_PER_PAGE = 50


class AdzunaNotConfiguredError(Exception):
    pass


class AdzunaSource(JobSource):
    source = JobSourceType.ADZUNA

    def __init__(self, http: PoliteHttpClient, app_id: str, app_key: str, max_pages: int = 2) -> None:
        self._http = http
        self._app_id = app_id
        self._app_key = app_key
        self._max_pages = max_pages

    @property
    def configured(self) -> bool:
        return bool(self._app_id and self._app_key)

    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]:
        if not isinstance(target, JobQuery):
            raise ValueError("Adzuna is searched with a JobQuery")
        if not self.configured:
            raise AdzunaNotConfiguredError("set ADZUNA_APP_ID and ADZUNA_APP_KEY")
        raws: list[RawJob] = []
        for page in range(1, self._max_pages + 1):
            params: dict[str, Any] = {
                "app_id": self._app_id,
                "app_key": self._app_key,
                "results_per_page": RESULTS_PER_PAGE,
                "what": target.what,
                "max_days_old": target.max_days_old,
                "sort_by": "date",
                "content-type": "application/json",
            }
            if target.where:
                params["where"] = target.where
            data = await self._http.get_json(f"{BASE_URL}/{page}", params=params)
            results = data.get("results") or []
            raws += [
                RawJob(
                    source=self.source,
                    external_id=str(r["id"]) if r.get("id") is not None else None,
                    payload=r,
                    company_name=(r.get("company") or {}).get("display_name"),
                )
                for r in results
                if isinstance(r, dict)
            ]
            if len(results) < RESULTS_PER_PAGE:
                break
        return raws

    def normalize(self, raw: RawJob) -> JobIn:
        job = raw.payload
        title = html_to_text(str(job.get("title") or ""))
        if not title:
            raise MalformedJobError("Adzuna result without a title")
        if not raw.company_name:
            raise MalformedJobError("Adzuna result without a company")
        location = (job.get("location") or {}).get("display_name")
        description = html_to_text(job.get("description"))
        hint = job.get("contract_time") or job.get("contract_type")
        return JobIn(
            source=self.source,
            external_id=raw.external_id,
            company_name=raw.company_name,
            title=title,
            location=location,
            remote=detect_remote(location) or (True if re.search(r"\bremote\b", title, re.I) else None),
            employment_type=detect_employment_type(title, hint),
            description_text=description,
            url=job.get("redirect_url"),
            posted_at=parse_datetime(job.get("created")),
        )
