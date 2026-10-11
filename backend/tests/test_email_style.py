"""Phase 6 follow-up: machine-sounding phrasing and copied text in drafts (services/email/style.py)."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.services.email.drafter import Drafter
from app.services.email.style import copied_run, style_issues
from app.services.llm.fake import FakeLLMClient
from tests.test_drafts import CONTEXT, _draft, _inputs, drafted  # noqa: F401 (fixture)

JD = (
    "You will build and maintain REST APIs in Python backed by PostgreSQL for our payments platform, "
    "working closely with senior engineers."
)


def _codes(body: str, subject: str = "Backend intern role at Ledgerline") -> list[str]:
    return [i.code for i in style_issues(subject, body, [JD])]


@pytest.mark.parametrize(
    "phrase",
    [
        "I hope this email finds you well.",
        "I came across the backend intern role.",
        "I noticed Ledgerline is looking for interns.",
        "I'm writing to ask about the role.",
        "As a third-year computer science student, I build backend services.",
        "I'm really excited about this role.",
        "I am passionate about backend work.",
        "The role stood out to me.",
        "My experience aligns perfectly with the team.",
        "I'd be a great fit for the team.",
        "I want to leverage my Python skills.",
        "I have honed my skills in Django.",
        "Furthermore, I wrote tests.",
        "It's not only fast but also correct.",
        "Thank you for your time and consideration.",
        "I look forward to hearing from you.",
        "I built a parser — and a CLI.",
        "Since your team is improving its CI pipeline, I set up CI tests.",
        "I set up CI tests, so this seemed relevant.",
        "This connects directly to my parser work.",
        "I have hands-on experience with Django.",
    ],
)
def test_machine_sounding_phrases_are_flagged(phrase: str) -> None:
    assert _codes(f"Would you refer me? {phrase} Resume attached.") == ["sounds_generated"]


@pytest.mark.parametrize(
    "body",
    [
        # The examples from prompts/draft_email.md.
        "I'm applying for the backend intern role and wanted to ask if you'd refer me. Most of what I've "
        "built is Python on Postgres, including a Django API for a college project, and I set up a "
        "90-question test set that runs in CI and stops merges when accuracy drops.\n\nIf you're not the "
        "right person for this, a pointer to whoever's hiring would help a lot. Resume's attached.",
        "Would you be open to referring me for the platform internship? I've spent the last year writing "
        "Go services and running them on a small Kubernetes cluster I set up myself. My resume's attached.",
        # Ordinary CS words and "As a result" aren't tells.
        "I mostly do dynamic programming problems and wrote a robust retry loop. As a result, my tests "
        "are fast. Could you refer me? Resume attached.",
    ],
)
def test_plain_writing_passes(body: str) -> None:
    assert _codes(body) == []


def test_template_subjects_are_flagged() -> None:
    assert _codes("Could you refer me? Resume attached.", subject="Backend Intern: Referral Request") == [
        "sounds_generated"
    ]
    assert _codes("Could you refer me? Resume attached.", subject="Quick question") == ["sounds_generated"]


def test_text_copied_from_the_posting_is_flagged() -> None:
    copied = "I'd like to build and maintain REST APIs in Python backed by PostgreSQL. Resume attached."
    assert copied_run(copied, [JD]) == "build and maintain rest apis in python backed"
    seven_words = "I'd like to build and maintain REST APIs in Go. Resume attached."
    assert copied_run(seven_words, [JD]) is None


async def test_phrasing_left_after_the_retry_becomes_a_warning_not_a_failure() -> None:
    sloppy = _draft(body="I'm excited to apply. Would you refer me for the role? My resume is attached.")
    llm = FakeLLMClient(responses={"draft_email": [sloppy.model_dump(), sloppy.model_dump()]})
    result = await Drafter(llm).draft(_inputs(), None)
    assert len(llm.calls) == 2
    assert "[sounds_generated]" in llm.calls[1][1]  # the retry was told what to fix
    assert len(result.style_warnings) == 1
    assert "excited" in result.style_warnings[0]


async def test_review_card_warns_about_phrasing_in_edits(
    with_hunter_key: AsyncClient,
    drafted: dict[str, Any],  # noqa: F811
) -> None:
    body = drafted["body"].replace("I'm applying", "I'm thrilled to be applying", 1)
    response = await with_hunter_key.patch(f"/outreach/{drafted['id']}", json={"body": body})
    assert response.status_code == 200, response.text  # the user's own words are never blocked
    [warning] = response.json()["style_warnings"]
    assert "thrilled" in warning
