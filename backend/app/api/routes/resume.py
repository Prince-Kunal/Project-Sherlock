import asyncio
import json
import uuid
from pathlib import Path, PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error, llm_errors
from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.db import get_session
from app.models import MasterResume as MasterResumeRow
from app.schemas.resume import MasterResume, ResumeOut, ResumeVersionOut, TaggedBullet
from app.services.llm.client import LLMClient
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.llm.user_keys import resolve_api_key
from app.services.registry import get_llm_client
from app.services.resume import store
from app.services.resume.ats_check import AtsExpectations, AtsReport, ats_check
from app.services.resume.parser import ResumeExtractionError, parse_resume
from app.services.resume.render import RenderError, render_resume, resume_filename
from app.services.resume.skills import get_lexicon

router = APIRouter(prefix="/resume", tags=["resume"])

Session = Annotated[AsyncSession, Depends(get_session)]
LLM = Annotated[LLMClient, Depends(get_llm_client)]

_ALLOWED_SUFFIXES = {".pdf", ".docx"}


def _out(row: MasterResumeRow) -> ResumeOut:
    return ResumeOut(version=row.version, data=MasterResume.model_validate(row.data))


async def _load(session: AsyncSession, user_id: uuid.UUID, version: int | None) -> MasterResumeRow:
    if version is None:
        row = await store.get_current(session, user_id)
    else:
        row = await store.get_version(session, user_id, version)
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "resume_not_found", "No resume yet. Upload one first.")
    return row


def _save_upload(user_id: uuid.UUID, suffix: str, data: bytes) -> str:
    directory = Path(get_settings().storage_dir) / str(user_id) / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    return str(path)


@router.post("/upload", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    user: CurrentUser, session: Session, llm: LLM, file: Annotated[UploadFile, File()]
) -> ResumeOut:
    suffix = PurePath(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported_file", "Upload a PDF or DOCX file."
        )
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise api_error(
            status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large", "The file must be 5 MB or smaller."
        )

    with llm_errors():
        api_key = await resolve_api_key(session, user.id)
        try:
            resume = await parse_resume(data, file.filename or f"resume{suffix}", llm, api_key)
        except ResumeExtractionError as exc:
            raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "unreadable_resume", str(exc)) from exc

    path = await asyncio.to_thread(_save_upload, user.id, suffix, data)
    row = await store.save_new_version(session, user.id, resume, source_file_path=path)
    await session.commit()
    return _out(row)


@router.get("", response_model=ResumeOut)
async def get_resume(user: CurrentUser, session: Session) -> ResumeOut:
    return _out(await _load(session, user.id, None))


@router.put("", response_model=ResumeOut)
async def save_resume(user: CurrentUser, session: Session, resume: MasterResume) -> ResumeOut:
    """Saving always creates a new version; earlier versions stay retrievable."""
    try:
        row = await store.save_new_version(session, user.id, resume)
    except ValueError as exc:
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_resume", str(exc)) from exc
    await session.commit()
    return _out(row)


@router.get("/versions", response_model=list[ResumeVersionOut])
async def list_versions(user: CurrentUser, session: Session) -> list[ResumeVersionOut]:
    return [
        ResumeVersionOut(version=r.version, is_current=r.is_current, created_at=r.created_at.isoformat())
        for r in await store.list_versions(session, user.id)
    ]


@router.get("/versions/{version}", response_model=ResumeOut)
async def get_version(version: int, user: CurrentUser, session: Session) -> ResumeOut:
    return _out(await _load(session, user.id, version))


async def _render(row: MasterResumeRow) -> tuple[bytes, AtsReport, str]:
    resume = MasterResume.model_validate(row.data)
    try:
        rendered = await render_resume(resume)
    except RenderError as exc:
        raise api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "render_failed", "Could not render the PDF."
        ) from exc
    report = await ats_check(rendered.pdf, AtsExpectations.from_rendered(rendered))
    return rendered.pdf, report, resume_filename(resume.basics.name)


@router.get("/preview.pdf", response_class=Response)
async def preview_pdf(user: CurrentUser, session: Session, version: int | None = None) -> Response:
    pdf, report, filename = await _render(await _load(session, user.id, version))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-ATS-Passed": "true" if report.passed else "false",
            "Cache-Control": "no-store",
        },
    )


@router.get("/ats-check", response_model=AtsReport)
async def preview_ats_check(user: CurrentUser, session: Session, version: int | None = None) -> AtsReport:
    _, report, _ = await _render(await _load(session, user.id, version))
    return report


class TagSkillsIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=40)


@router.post("/tag-skills", response_model=list[TaggedBullet])
async def tag_skills(body: TagSkillsIn, user: CurrentUser, session: Session, llm: LLM) -> list[TaggedBullet]:
    """Suggest skill tags for new or edited bullets (one LLM request for the whole batch)."""
    current = await store.get_current(session, user.id)
    skills_section = (
        "\n".join(f"{k}: {', '.join(v)}" for k, v in MasterResume.model_validate(current.data).skills.items())
        if current
        else "(none)"
    )
    bullets = json.dumps([{"index": i, "text": redact_pii(t)} for i, t in enumerate(body.texts)])
    with llm_errors():
        api_key = await resolve_api_key(session, user.id)
        request = load_prompt("tag_skills").request(
            tier="fast", api_key=api_key, skills_section=skills_section, bullets=bullets
        )
        tagged = await llm.generate(request, list[TaggedBullet])
    lexicon = get_lexicon()
    by_index = {t.index: t for t in tagged if 0 <= t.index < len(body.texts)}
    return [
        TaggedBullet(index=i, skills=lexicon.normalize_all(by_index[i].skills if i in by_index else []))
        for i in range(len(body.texts))
    ]
