from typing import Any

from httpx import AsyncClient

from app.services.llm.fake import FakeLLMClient
from tests.conftest import FIXTURES, recorded


async def _upload(client: AsyncClient, fake_llm: FakeLLMClient) -> dict[str, Any]:
    fake_llm.add_response("parse_resume", recorded("parse_resume", "aarav_menon"))
    path = FIXTURES / "resumes" / "aarav_menon.pdf"
    response = await client.post(
        "/resume/upload", files={"file": (path.name, path.read_bytes(), "application/pdf")}
    )
    assert response.status_code == 201
    data: dict[str, Any] = response.json()["data"]
    return data


async def test_edit_creates_version_n_plus_1_and_keeps_history(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    v1 = await _upload(with_llm_key, fake_llm)
    original_text = v1["projects"][0]["bullets"][0]["text"]

    edited = {**v1}
    edited["projects"][0]["bullets"][0]["text"] = "Built an IoT pen with an ESP32 microcontroller."
    edited["projects"][0]["bullets"][0]["pinned"] = True
    response = await with_llm_key.put("/resume", json=edited)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2

    current = (await with_llm_key.get("/resume")).json()
    assert current["version"] == 2
    assert current["data"]["projects"][0]["bullets"][0]["pinned"] is True

    previous = (await with_llm_key.get("/resume/versions/1")).json()
    assert previous["data"]["projects"][0]["bullets"][0]["text"] == original_text

    versions = (await with_llm_key.get("/resume/versions")).json()
    assert [(v["version"], v["is_current"]) for v in versions] == [(2, True), (1, False)]


async def test_new_bullets_get_ids_and_existing_ids_survive_reordering(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    v1 = await _upload(with_llm_key, fake_llm)
    bullets = v1["projects"][0]["bullets"]
    original_ids = [b["id"] for b in bullets]
    v1["projects"][0]["bullets"] = [
        *reversed(bullets),
        {"id": "", "text": "Wrote unit tests for the DTW matcher.", "skills": ["Python3"], "pinned": False},
    ]
    saved = (await with_llm_key.put("/resume", json=v1)).json()["data"]["projects"][0]["bullets"]

    assert [b["id"] for b in saved[:-1]] == list(reversed(original_ids))
    new = saved[-1]
    assert new["id"] == f"proj1-b{len(original_ids) + 1}"
    assert new["skills"] == ["python"]  # normalised via the alias map on save


async def test_new_entry_gets_an_id(with_llm_key: AsyncClient, fake_llm: FakeLLMClient) -> None:
    v1 = await _upload(with_llm_key, fake_llm)
    v1["experience"].append(
        {"id": "", "org": "Example Co", "role": "Intern", "bullets": [{"id": "", "text": "Did a thing."}]}
    )
    saved = (await with_llm_key.put("/resume", json=v1)).json()["data"]["experience"]
    assert saved[-1]["id"] == "exp2"
    assert saved[-1]["bullets"][0]["id"] == "exp2-b1"


async def test_duplicate_ids_rejected(with_llm_key: AsyncClient, fake_llm: FakeLLMClient) -> None:
    v1 = await _upload(with_llm_key, fake_llm)
    v1["achievements"][1]["id"] = v1["achievements"][0]["id"]
    response = await with_llm_key.put("/resume", json=v1)
    assert response.status_code == 422


async def test_bad_date_format_rejected(with_llm_key: AsyncClient, fake_llm: FakeLLMClient) -> None:
    v1 = await _upload(with_llm_key, fake_llm)
    v1["education"][0]["start"] = "Aug 2024"
    assert (await with_llm_key.put("/resume", json=v1)).status_code == 422


async def test_resume_before_upload_is_404(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/resume")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resume_not_found"


async def test_users_cannot_see_each_others_resumes(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient, other_user_headers: dict[str, str]
) -> None:
    """Invariant 5."""
    await _upload(with_llm_key, fake_llm)
    with_llm_key.cookies.clear()
    for path in ["/resume", "/resume/versions/1", "/resume/preview.pdf", "/resume/ats-check"]:
        response = await with_llm_key.get(path, headers=other_user_headers)
        assert response.status_code == 404, path
    assert (await with_llm_key.get("/resume/versions", headers=other_user_headers)).json() == []


async def test_resume_routes_require_auth(client: AsyncClient) -> None:
    for method, path in [
        ("GET", "/resume"),
        ("PUT", "/resume"),
        ("POST", "/resume/upload"),
        ("GET", "/resume/versions"),
        ("GET", "/resume/preview.pdf"),
        ("GET", "/preferences"),
        ("GET", "/settings/llm-key"),
    ]:
        assert (await client.request(method, path)).status_code == 401, path
