"""Open-outreach fixtures (PLAN.md Phase 8): companies from the recorded YC directory slice, a prospect
target for the matching-fixture user (Rohan), and the company the recorded open draft is about."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CompanyMatch, ProspectTarget
from app.models.enums import CompanyMatchStatus
from app.services.prospects.discovery import upsert_company
from app.services.prospects.fake import load_yc_fixture

# The recorded open-outreach draft (tests/fixtures/llm/draft_open_email) is to this company.
OPEN_DRAFT_DOMAIN = "abstra.io"
TARGET_NAME = "Indian startups"


def yc_companies() -> list[Company]:
    """Unsaved Company rows for every usable entry of the YC fixture (for prompts and recorders)."""
    rows = []
    for found in load_yc_fixture():
        rows.append(
            Company(
                name=found.name,
                domain=found.domain,
                description=found.description,
                industry=found.industry,
                industry_tags=found.industry_tags,
                locations=found.locations,
                hq_location=found.hq_location,
                employee_count=found.employee_count,
                size_hint=found.size_hint,
            )
        )
    return rows


async def seed_yc_companies(session: AsyncSession) -> dict[str, Company]:
    """Upsert the fixture companies; returns them by domain."""
    companies = {}
    for found in load_yc_fixture():
        company, _ = await upsert_company(session, found)
        companies[company.domain or company.name] = company
    await session.commit()
    return companies


async def add_target(session: AsyncSession, user_id: uuid.UUID, **values: object) -> ProspectTarget:
    fields: dict[str, object] = {
        "name": TARGET_NAME,
        "target_roles": ["Backend Intern"],
        "contact_titles": ["CTO", "Engineering Manager"],
        "industries": [],
        "locations": ["India"],
        "company_sizes": ["startup"],
    }
    target = ProspectTarget(user_id=user_id, **{**fields, **values})
    session.add(target)
    await session.commit()
    return target


async def add_company_match(
    session: AsyncSession,
    user_id: uuid.UUID,
    company: Company,
    target: ProspectTarget,
    score: int = 82,
    angle: str = "Your Python backend work is close to what this company builds.",
) -> CompanyMatch:
    match = CompanyMatch(
        user_id=user_id,
        company_id=company.id,
        prospect_target_id=target.id,
        score=score,
        angle=angle,
        reasoning="Fixture match.",
        status=CompanyMatchStatus.NEW,
    )
    session.add(match)
    await session.commit()
    return match
