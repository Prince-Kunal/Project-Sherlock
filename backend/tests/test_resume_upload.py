"""Phase 1 acceptance: uploading the 3 fixture resumes produces valid MasterResume objects
(fake LLM replaying real recorded Gemini outputs)."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.schemas.resume import MasterResume
from app.services.llm.fake import FakeLLMClient
from tests.conftest import FIXTURES, recorded

RESUMES = FIXTURES / "resumes"
USER_KEY = "AIza-test-key-1234567890"

CASES = [
    # file, expected email, expected phone, expected profile links (display form)
    (
        "aarav_menon.pdf",
        "aarav.menon@example.com",
        "+91 90000 11111",
        {"linkedin.com/in/aarav-menon-dev", "github.com/aaravmenon", "leetcode.com/u/aaravm"},
    ),
    (
        "meera_iyer.pdf",
        "meera.iyer@example.com",
        "+91 90000 22222",
        {"linkedin.com/in/meera-iyer-robotics", "github.com/meeraiyer"},
    ),
    (
        "rohan_das.docx",
        "rohan.das@example.com",
        "+91 90000 33333",
        {"linkedin.com/in/rohandas-oss", "github.com/rohan-das-oss", "rohandas.example.dev"},
    ),
]


def _upload(path: Path) -> dict[str, tuple[str, bytes, str]]:
    content_type = (
        "application/pdf"
        if path.suffix == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return {"file": (path.name, path.read_bytes(), content_type)}


@pytest.mark.parametrize(("filename", "email", "phone", "links"), CASES)
async def test_fixture_resume_upload_produces_valid_master_resume(
    with_llm_key: AsyncClient,
    fake_llm: FakeLLMClient,
    filename: str,
    email: str,
    phone: str,
    links: set[str],
) -> None:
    fake_llm.add_response("parse_resume", recorded("parse_resume", Path(filename).stem))

    response = await with_llm_key.post("/resume/upload", files=_upload(RESUMES / filename))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 1
    resume = MasterResume.model_validate(body["data"])

    # Contact details were found deterministically and re-inserted.
    assert resume.basics.email == email
    assert resume.basics.phone == phone
    shown = {link.url.split("://", 1)[-1].removeprefix("www.").rstrip("/") for link in resume.basics.links}
    assert shown == links

    # Stable, unique ids on every entry and bullet; skills are canonical lowercase.
    assert resume.all_bullets()
    for entry in resume.entries():
        for i, bullet in enumerate(entry.bullets, start=1):
            assert bullet.id == f"{entry.id}-b{i}"
    for bullet in resume.all_bullets():
        assert all(skill == skill.lower() for skill in bullet.skills)

    # The prompt sent to the LLM never contained the email or phone number (PLAN.md §3.1).
    request, prompt = fake_llm.calls[-1]
    assert request.prompt_name == "parse_resume"
    assert request.api_key == USER_KEY  # the user's own key, not the owner's
    assert email not in prompt
    assert phone.replace(" ", "") not in prompt.replace(" ", "")


async def test_hidden_links_are_sent_as_link_targets(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    """Aarav's resume shows only the words "LinkedIn"/"GitHub"; the URLs live in link annotations."""
    fake_llm.add_response("parse_resume", recorded("parse_resume", "aarav_menon"))
    await with_llm_key.post("/resume/upload", files=_upload(RESUMES / "aarav_menon.pdf"))
    _, prompt = fake_llm.calls[-1]
    assert "https://github.com/aaravmenon" in prompt


async def test_known_skill_aliases_are_canonicalised(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    fake_llm.add_response("parse_resume", recorded("parse_resume", "meera_iyer"))
    response = await with_llm_key.post("/resume/upload", files=_upload(RESUMES / "meera_iyer.pdf"))
    resume = MasterResume.model_validate(response.json()["data"])
    all_skills = {s for b in resume.all_bullets() for s in b.skills}
    assert "ros 2" in all_skills
    assert "isaac sim" not in all_skills  # alias → "nvidia isaac sim"


async def test_upload_requires_llm_key(auth_client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    response = await auth_client.post("/resume/upload", files=_upload(RESUMES / "aarav_menon.pdf"))
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "llm_key_required"
    assert fake_llm.calls == []


async def test_owner_key_fallback_when_allowed(
    auth_client: AsyncClient, fake_llm: FakeLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "allow_owner_key_fallback", True)
    fake_llm.add_response("parse_resume", recorded("parse_resume", "aarav_menon"))
    response = await auth_client.post("/resume/upload", files=_upload(RESUMES / "aarav_menon.pdf"))
    assert response.status_code == 201
    assert fake_llm.calls[-1][0].api_key is None  # None = owner's key


async def test_rejects_unsupported_file_type(with_llm_key: AsyncClient) -> None:
    response = await with_llm_key.post(
        "/resume/upload", files={"file": ("resume.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 415


async def test_rejects_files_over_5_mb(with_llm_key: AsyncClient) -> None:
    big = b"%PDF-1.7\n" + b"0" * (5 * 1024 * 1024)
    response = await with_llm_key.post("/resume/upload", files={"file": ("big.pdf", big, "application/pdf")})
    assert response.status_code == 413


async def test_scanned_pdf_is_rejected_without_llm_call(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    scan = (FIXTURES / "ats" / "image_only.pdf").read_bytes()
    calls_before = len(fake_llm.calls)
    response = await with_llm_key.post(
        "/resume/upload", files={"file": ("scan.pdf", scan, "application/pdf")}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unreadable_resume"
    assert len(fake_llm.calls) == calls_before


async def test_invalid_llm_output_twice_returns_502(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    fake_llm.add_response("parse_resume", ['{"basics": {}}', '{"basics": {}}'])
    response = await with_llm_key.post("/resume/upload", files=_upload(RESUMES / "aarav_menon.pdf"))
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "llm_bad_output"
    assert (await with_llm_key.get("/resume")).status_code == 404  # nothing saved


async def test_upload_stores_source_file(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient, storage_dir: Path
) -> None:
    fake_llm.add_response("parse_resume", recorded("parse_resume", "rohan_das"))
    await with_llm_key.post("/resume/upload", files=_upload(RESUMES / "rohan_das.docx"))
    stored = list(storage_dir.rglob("*.docx"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == (RESUMES / "rohan_das.docx").read_bytes()
