"""Master resume versioning: every save is a new row; the newest is `is_current`. History is kept.
Every query filters by user_id (invariant 5)."""

import re
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MasterResume as MasterResumeRow
from app.schemas.resume import Bullet, MasterResume
from app.services.resume.skills import get_lexicon


async def get_current(session: AsyncSession, user_id: uuid.UUID) -> MasterResumeRow | None:
    result = await session.execute(
        select(MasterResumeRow).where(MasterResumeRow.user_id == user_id, MasterResumeRow.is_current)
    )
    return result.scalar_one_or_none()


async def get_version(session: AsyncSession, user_id: uuid.UUID, version: int) -> MasterResumeRow | None:
    result = await session.execute(
        select(MasterResumeRow).where(MasterResumeRow.user_id == user_id, MasterResumeRow.version == version)
    )
    return result.scalar_one_or_none()


async def list_versions(session: AsyncSession, user_id: uuid.UUID) -> list[MasterResumeRow]:
    result = await session.execute(
        select(MasterResumeRow)
        .where(MasterResumeRow.user_id == user_id)
        .order_by(MasterResumeRow.version.desc())
    )
    return list(result.scalars())


def _next_id(prefix: str, taken: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    taken.add(f"{prefix}{n}")
    return f"{prefix}{n}"


def assign_missing_ids(resume: MasterResume) -> MasterResume:
    """Give new entries/bullets (sent with an empty id) a fresh stable id. Existing ids never change,
    so a bullet keeps its id through edits and reordering."""
    taken = set(resume.all_ids())
    for prefix, entries in (("edu", resume.education), ("exp", resume.experience), ("proj", resume.projects)):
        for entry in entries:
            if not entry.id.strip():
                entry.id = _next_id(prefix, taken)
            _fill_bullets(f"{entry.id}-b", entry.bullets, taken)
    _fill_bullets("ach-b", resume.achievements, taken)
    return resume


def _fill_bullets(prefix: str, bullets: list[Bullet], taken: set[str]) -> None:
    for bullet in bullets:
        if not bullet.id.strip():
            bullet.id = _next_id(prefix, taken)


def normalise(resume: MasterResume) -> MasterResume:
    lexicon = get_lexicon()
    for bullet in resume.all_bullets():
        bullet.text = re.sub(r"\s+", " ", bullet.text).strip()
        bullet.skills = lexicon.normalize_all(bullet.skills)
    if resume.basics.email:
        resume.basics.email = resume.basics.email.strip().lower()
    return assign_missing_ids(resume)


async def save_new_version(
    session: AsyncSession,
    user_id: uuid.UUID,
    resume: MasterResume,
    source_file_path: str | None = None,
) -> MasterResumeRow:
    """Store `resume` as version N+1 and make it current. Caller commits."""
    resume = normalise(resume)
    # Re-validate: id assignment must not have produced duplicates.
    data: dict[str, Any] = MasterResume.model_validate(resume.model_dump()).model_dump(mode="json")
    current_max = await session.scalar(
        select(func.max(MasterResumeRow.version)).where(MasterResumeRow.user_id == user_id)
    )
    if source_file_path is None:
        previous = await get_current(session, user_id)
        source_file_path = previous.source_file_path if previous else None
    await session.execute(
        update(MasterResumeRow)
        .where(MasterResumeRow.user_id == user_id, MasterResumeRow.is_current)
        .values(is_current=False)
    )
    row = MasterResumeRow(
        user_id=user_id,
        version=(current_max or 0) + 1,
        data=data,
        is_current=True,
        source_file_path=source_file_path,
    )
    session.add(row)
    await session.flush()
    return row
