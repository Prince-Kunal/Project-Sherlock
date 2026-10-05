from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error, llm_errors
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import Company, Job, UserCompanyBlock, UserPreferences
from app.schemas.jobs import CompanyBrief, EmploymentFilter, JobFeed, JobOut, ManualJobIn
from app.services.jobs.companies import find_or_create_company
from app.services.jobs.ingest import upsert_jobs
from app.services.llm.client import LLMClient
from app.services.llm.user_keys import resolve_api_key
from app.services.registry import get_llm_client, get_source_http
from app.services.sources.base import MalformedJobError
from app.services.sources.http import PoliteHttpClient, SourceHTTPError
from app.services.sources.manual import ManualJobResolver, NotAJobPostingError

router = APIRouter(prefix="/jobs", tags=["jobs"])

Session = Annotated[AsyncSession, Depends(get_session)]
_effective = func.coalesce(Job.posted_at, Job.first_seen_at)


def _out(job: Job, company: Company, now: datetime) -> JobOut:
    effective = job.posted_at or job.first_seen_at
    return JobOut(
        id=job.id,
        title=job.title,
        company=CompanyBrief.model_validate(company),
        location=job.location,
        remote=job.remote,
        employment_type=job.employment_type,
        url=job.url,
        source=job.source.value,
        posted_at=job.posted_at,
        first_seen_at=job.first_seen_at,
        effective_date=effective,
        age_days=max(0, (now - effective).days),
    )


@router.get("", response_model=JobFeed)
async def job_feed(
    user: CurrentUser,
    session: Session,
    max_age_days: Annotated[int | None, Query(ge=1, le=60)] = None,
    employment_type: EmploymentFilter | None = None,
    remote: bool | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobFeed:
    """Active jobs no older than the user's max_job_age_days (a smaller `max_age_days` narrows it)."""
    prefs_limit = await session.scalar(
        select(UserPreferences.max_job_age_days).where(UserPreferences.user_id == user.id)
    )
    age_limit = min(max_age_days or prefs_limit or 14, prefs_limit or 14)
    now = datetime.now(UTC)

    blocked = select(UserCompanyBlock.company_id).where(UserCompanyBlock.user_id == user.id)
    conditions = [
        Job.is_active,
        _effective >= now - timedelta(days=age_limit),
        Job.company_id.not_in(blocked),
    ]
    if employment_type:
        conditions.append(Job.employment_type == employment_type)
    if remote is not None:
        conditions.append(Job.remote.is_(remote))
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(Job.title.ilike(pattern), Company.name.ilike(pattern), Job.location.ilike(pattern))
        )

    base = select(Job, Company).join(Company, Company.id == Job.company_id).where(*conditions)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await session.execute(base.order_by(_effective.desc(), Job.id).limit(limit).offset(offset))).all()
    return JobFeed(
        items=[_out(job, company, now) for job, company in rows], total=total, max_age_days=age_limit
    )


@router.post("/manual", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def add_manual_job(
    body: ManualJobIn,
    user: CurrentUser,
    session: Session,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    http: Annotated[PoliteHttpClient, Depends(get_source_http)],
) -> JobOut:
    """Add a job by URL. Greenhouse/Lever/Ashby links use their APIs; other pages are read by the LLM."""
    url = str(body.url)
    resolver = ManualJobResolver(http, llm)
    try:
        with llm_errors():
            api_key = await resolve_api_key(session, user.id)
            manual = await resolver.resolve(url, api_key)
    except SourceHTTPError as exc:
        code = status.HTTP_404_NOT_FOUND if exc.status == 404 else status.HTTP_502_BAD_GATEWAY
        raise api_error(
            code, "job_fetch_failed", f"Couldn't load that job ({exc.status or 'network error'})."
        ) from exc
    except (NotAJobPostingError, MalformedJobError) as exc:
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_a_job", str(exc)) from exc

    job_in = manual.job
    if manual.ats:
        company = await find_or_create_company(
            session,
            name=job_in.company_name,
            domain=job_in.company_domain,
            ats_type=manual.ats.ats,
            ats_token=manual.ats.token,
        )
    else:
        company = await find_or_create_company(
            session, name=job_in.company_name, domain=job_in.company_domain
        )
    now = datetime.now(UTC)
    result = await upsert_jobs(session, company, [job_in], now)
    await session.commit()
    job = await session.get(Job, (result.job_ids or [])[0])
    if job is None:  # pragma: no cover - the upsert just returned this id
        raise api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "job_missing", "Job vanished after saving.")
    return _out(job, company, now)
