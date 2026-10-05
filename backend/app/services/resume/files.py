"""Where generated resume PDFs live (PLAN.md Phase 4): STORAGE_DIR/{user_id}/{folder}/{filename},
where folder is the outreach id (or previews/{match_id} for previews) and filename is the one the
recipient sees, `Firstname_Lastname_Resume.pdf`."""

import asyncio
import uuid
from pathlib import Path

from app.core.config import get_settings


def tailored_pdf_path(user_id: uuid.UUID, folder: str, filename: str) -> Path:
    return Path(get_settings().storage_dir) / str(user_id) / folder / filename


def preview_folder(match_id: uuid.UUID) -> str:
    return f"previews/{match_id}"


def _write(path: Path, pdf: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob("*.pdf"):  # one PDF per folder: a renamed user leaves no stale file
        old.unlink()
    path.write_bytes(pdf)


async def save_tailored_pdf(user_id: uuid.UUID, folder: str, filename: str, pdf: bytes) -> Path:
    path = tailored_pdf_path(user_id, folder, filename)
    await asyncio.to_thread(_write, path, pdf)
    return path


def find_pdf(user_id: uuid.UUID, folder: str) -> Path | None:
    directory = Path(get_settings().storage_dir) / str(user_id) / folder
    return next(iter(sorted(directory.glob("*.pdf"))), None) if directory.is_dir() else None
