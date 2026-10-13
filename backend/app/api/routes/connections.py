"""Warm paths (PLAN.md Phase 10): upload, view and delete your own connections list."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import UserConnection
from app.schemas.connections import ConnectionsSummary
from app.services.connections import (
    ConnectionsFileError,
    connections_summary,
    parse_connections_csv,
    replace_connections,
)

router = APIRouter(prefix="/connections", tags=["connections"])

Session = Annotated[AsyncSession, Depends(get_session)]
MAX_BYTES = 5 * 1024 * 1024


async def _summary(session: AsyncSession, user_id: uuid.UUID) -> ConnectionsSummary:
    count, companies, alumni = await connections_summary(session, user_id)
    uploaded = await session.scalar(
        select(func.max(UserConnection.created_at)).where(UserConnection.user_id == user_id)
    )
    return ConnectionsSummary(count=count, companies=companies, alumni=alumni, uploaded_at=uploaded)


@router.get("", response_model=ConnectionsSummary)
async def get_connections(user: CurrentUser, session: Session) -> ConnectionsSummary:
    return await _summary(session, user.id)


@router.post("", response_model=ConnectionsSummary)
async def upload_connections(
    user: CurrentUser, session: Session, file: Annotated[UploadFile, File()]
) -> ConnectionsSummary:
    """Replace the list with a CSV: LinkedIn's Connections.csv, or any file with name and company
    columns (and optionally school, position, profile URL)."""
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise api_error(
            status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large", "The file must be 5 MB or smaller."
        )
    try:
        people = parse_connections_csv(data)
    except ConnectionsFileError as exc:
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_connections_file", str(exc)) from exc
    if not people:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_connections_file", "No people in the file."
        )
    await replace_connections(session, user.id, people)
    await session.commit()
    return await _summary(session, user.id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connections(user: CurrentUser, session: Session) -> None:
    await replace_connections(session, user.id, [])
    await session.commit()
