"""POST /jobs/manual {url}: turn a pasted job URL into a JobIn (also what the browser extension sends).

Greenhouse, Lever, Ashby, SmartRecruiters, Workable and Recruitee posting URLs are fetched through
their public APIs (deterministic, no LLM). Any other page is fetched, cleaned with readability, and
parsed by the fast LLM model.
"""

import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel
from readability import Document

from app.models.enums import AtsType, JobSourceType
from app.services.llm.client import LLMClient
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.sources.ashby import AshbySource
from app.services.sources.base import JobIn, MalformedJobError, RawJob
from app.services.sources.greenhouse import GreenhouseSource
from app.services.sources.http import PoliteHttpClient
from app.services.sources.lever import LeverSource
from app.services.sources.recruitee import RecruiteeSource
from app.services.sources.smartrecruiters import SmartRecruitersSource
from app.services.sources.text import (
    company_domain_from_url,
    detect_employment_type,
    detect_remote,
    html_to_text,
)
from app.services.sources.workable import WorkableSource

_GREENHOUSE_RE = re.compile(r"^(?:job-boards(?:\.eu)?|boards(?:\.eu)?)\.greenhouse\.io$")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class NotAJobPostingError(Exception):
    pass


@dataclass(frozen=True)
class AtsLink:
    ats: AtsType
    token: str
    job_id: str


def parse_ats_url(url: str) -> AtsLink | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)
    if _GREENHOUSE_RE.match(host):
        if len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
            return AtsLink(AtsType.GREENHOUSE, parts[0], parts[2])
        if "for" in query and ("token" in query or "gh_jid" in query):  # embed URLs
            job_id = (query.get("token") or query.get("gh_jid") or [""])[0]
            if job_id.isdigit():
                return AtsLink(AtsType.GREENHOUSE, query["for"][0], job_id)
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and len(parts) >= 2 and re.fullmatch(_UUID, parts[1]):
        return AtsLink(AtsType.LEVER, parts[0], parts[1])
    if host == "jobs.ashbyhq.com" and len(parts) >= 2 and re.fullmatch(_UUID, parts[1]):
        return AtsLink(AtsType.ASHBY, parts[0], parts[1])
    sr_host = host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}
    if sr_host and len(parts) >= 2 and (posting := re.match(r"^(\d+)", parts[1])):
        return AtsLink(AtsType.SMARTRECRUITERS, parts[0], posting.group(1))
    if host == "apply.workable.com" and len(parts) >= 3 and parts[1] == "j":
        return AtsLink(AtsType.WORKABLE, parts[0], parts[2])
    if host.endswith(".recruitee.com") and len(parts) >= 2 and parts[0] == "o":
        return AtsLink(AtsType.RECRUITEE, host.removesuffix(".recruitee.com"), parts[1])
    return None


class ParsedJobPage(BaseModel):
    is_job_posting: bool
    company: str | None = None
    title: str | None = None
    location: str | None = None
    remote: bool | None = None
    employment_type: Literal["internship", "full_time", "part_time", "contract"] | None = None


@dataclass
class ManualJob:
    job: JobIn
    ats: AtsLink | None  # set when the posting came from a known ATS board


class _SingleJobSource(Protocol):
    async def fetch_job(self, token: str, job_id: str) -> RawJob: ...

    def normalize(self, raw: RawJob) -> JobIn: ...


class ManualJobResolver:
    def __init__(self, http: PoliteHttpClient, llm: LLMClient) -> None:
        self._http = http
        self._llm = llm
        self._sources: dict[AtsType, _SingleJobSource] = {
            AtsType.GREENHOUSE: GreenhouseSource(http),
            AtsType.LEVER: LeverSource(http),
            AtsType.ASHBY: AshbySource(http),
            AtsType.SMARTRECRUITERS: SmartRecruitersSource(http),
            AtsType.WORKABLE: WorkableSource(http),
            AtsType.RECRUITEE: RecruiteeSource(http),
        }

    async def resolve(self, url: str, api_key: str | None) -> ManualJob:
        link = parse_ats_url(url)
        if link is not None:
            return ManualJob(job=await self._from_ats(link, url), ats=link)
        return ManualJob(job=await self._from_page(url, api_key), ats=None)

    async def _from_ats(self, link: AtsLink, url: str) -> JobIn:
        source = self._sources[link.ats]
        job = source.normalize(await source.fetch_job(link.token, link.job_id))
        return job.model_copy(
            update={
                "source": JobSourceType.MANUAL,
                "external_id": f"{link.ats.value}:{link.job_id}",
                "url": job.url or url,
            }
        )

    async def _from_page(self, url: str, api_key: str | None) -> JobIn:
        response = await self._http.get(url, headers={"Accept": "text/html"})
        if "html" not in response.headers.get("content-type", "html"):
            raise NotAJobPostingError("that URL is not a web page")
        document = Document(response.text)
        page_title = document.short_title() or ""
        page_text = html_to_text(document.summary())
        if len(page_text) < 200:
            raise NotAJobPostingError("couldn't find a job description on that page")
        request = load_prompt("parse_job_page").request(
            tier="fast",
            api_key=api_key,
            url=url,
            page_title=page_title,
            page_text=redact_pii(page_text)[:8000],
        )
        parsed = await self._llm.generate(request, ParsedJobPage)
        if not parsed.is_job_posting or not parsed.title or not parsed.company:
            raise NotAJobPostingError("that page doesn't look like a single job posting")
        try:
            return JobIn(
                source=JobSourceType.MANUAL,
                external_id=None,
                company_name=parsed.company,
                company_domain=company_domain_from_url(url),
                title=parsed.title,
                location=parsed.location,
                remote=parsed.remote if parsed.remote is not None else detect_remote(parsed.location),
                employment_type=parsed.employment_type or detect_employment_type(parsed.title),
                description_text=page_text,
                url=url,
            )
        except ValueError as exc:
            raise MalformedJobError(str(exc)) from exc
