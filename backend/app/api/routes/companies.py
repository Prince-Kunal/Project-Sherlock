"""Per-user company blocks (PLAN.md Phase 3): a blocked company's jobs leave the feed and matches."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import Company, UserCompanyBlock
from app.schemas.jobs import CompanyBrief

router = APIRouter(prefix="/companies", tags=["companies"])

Session = Annotated[AsyncSession, Depends(get_session)]


class BlockedCompany(BaseModel):
    company: CompanyBrief
    blocked: bool


async def _company(session: AsyncSession, company_id: uuid.UUID) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "company_not_found", "Company not found.")
    return company


@router.get("/blocked", response_model=list[CompanyBrief])
async def list_blocked(user: CurrentUser, session: Session) -> list[CompanyBrief]:
    rows = await session.scalars(
        select(Company)
        .join(UserCompanyBlock, UserCompanyBlock.company_id == Company.id)
        .where(UserCompanyBlock.user_id == user.id)
        .order_by(Company.name)
    )
    return [CompanyBrief.model_validate(c) for c in rows]


@router.post("/{company_id}/block", response_model=BlockedCompany)
async def block_company(company_id: uuid.UUID, user: CurrentUser, session: Session) -> BlockedCompany:
    company = await _company(session, company_id)
    await session.execute(
        insert(UserCompanyBlock)
        .values(user_id=user.id, company_id=company.id)
        .on_conflict_do_nothing(index_elements=[UserCompanyBlock.user_id, UserCompanyBlock.company_id])
    )
    await session.commit()
    return BlockedCompany(company=CompanyBrief.model_validate(company), blocked=True)


@router.delete("/{company_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_company(company_id: uuid.UUID, user: CurrentUser, session: Session) -> Response:
    await _company(session, company_id)
    await session.execute(
        delete(UserCompanyBlock).where(
            UserCompanyBlock.user_id == user.id, UserCompanyBlock.company_id == company_id
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
