import math
import uuid

from app.models.enums import AtsType, VerificationStatus
from app.services.contacts.fake import FakeContactProvider
from app.services.email.fake_gmail import FakeGmailClient
from app.services.email.gmail import Attachment, OutgoingEmail
from app.services.embeddings.fake import FakeEmbedder
from app.services.sources.base import CompanyRef
from app.services.sources.fake import FakeJobSource


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_fake_embedder_is_deterministic_normalised_and_meaningful() -> None:
    embedder = FakeEmbedder()
    a1, a2, related, unrelated = await embedder.embed(
        [
            "python backend engineer postgresql",
            "python backend engineer postgresql",
            "backend engineer python django",
            "pastry chef croissant bakery",
        ]
    )
    assert len(a1) == 384
    assert a1 == a2
    assert math.isclose(math.sqrt(sum(v * v for v in a1)), 1.0)
    assert _cosine(a1, related) > _cosine(a1, unrelated)


async def test_fake_contact_provider() -> None:
    provider = FakeContactProvider()
    result = await provider.search_people(domain="acme.dev")
    assert result.domain == "acme.dev"
    assert [p.email for p in result.people][:2] == ["asha@acme.dev", "vikram@acme.dev"]
    by_name = await provider.search_people(company="Acme Robotics")
    assert by_name.domain == "acmerobotics.example"
    email = await provider.find_email("acme.dev", "Neha", "Kapoor")
    assert email.email == "neha@acme.dev"
    assert await provider.verify("neha@acme.dev") == VerificationStatus.VALID
    assert await provider.verify("invalid.person@acme.dev") == VerificationStatus.INVALID
    assert await provider.verify("catchall@acme.dev") == VerificationStatus.ACCEPT_ALL
    assert [c[0] for c in provider.calls] == [
        "search_people",
        "search_people",
        "find_email",
        "verify",
        "verify",
        "verify",
    ]


async def test_fake_gmail_send_reply_and_thread() -> None:
    gmail = FakeGmailClient("me@gmail.com")
    sent = await gmail.send(
        OutgoingEmail(
            to="em@acme.dev",
            subject="Referral",
            body="Hi",
            attachment=Attachment(filename="Jane_Doe_Resume.pdf", data=b"%PDF"),
        )
    )
    gmail.add_message(sent.thread_id, "em@acme.dev", "Happy to refer you!")
    followup = await gmail.send(
        OutgoingEmail(to="em@acme.dev", subject="Re: Referral", body="Thanks", thread_id=sent.thread_id)
    )
    assert followup.thread_id == sent.thread_id
    thread = await gmail.get_thread(sent.thread_id)
    assert [m.from_address for m in thread] == ["me@gmail.com", "em@acme.dev", "me@gmail.com"]
    assert len(gmail.sent) == 2


async def test_fake_job_source_normalises() -> None:
    source = FakeJobSource()
    company = CompanyRef(id=uuid.uuid4(), name="Acme", domain="acme.dev", ats_type=AtsType.GREENHOUSE)
    raws = await source.fetch(company)
    jobs = [source.normalize(r) for r in raws]
    assert len(jobs) == 3
    assert jobs[0].company_domain == "acme.dev"
    assert jobs[0].employment_type == "internship"
    assert jobs[1].remote is True
    assert all(j.posted_at is not None for j in jobs)


async def test_fake_mode_scores_whatever_jobs_the_match_prompt_contains() -> None:
    from app.schemas.matches import ScoredJob
    from app.services.llm.prompt_loader import load_prompt
    from app.services.registry import build_fake_llm_client

    request = load_prompt("match").request(
        tier="fast", candidate="{}", jobs='[{"job_ref": "0123abcd"}, {"job_ref": "fedc9876"}]'
    )
    scores = await build_fake_llm_client().generate(request, list[ScoredJob])
    assert [s.job_ref for s in scores] == ["0123abcd", "fedc9876"]  # not the prompt's example ref
    assert all(40 <= s.fit_score <= 95 for s in scores)


async def test_fake_mode_tailors_any_resume() -> None:
    from app.services.registry import build_fake_llm_client
    from app.services.resume.tailor import Tailor
    from tests.tailor_fixtures import master
    from tests.test_tailor import _job

    job, company = _job()
    result = await Tailor(build_fake_llm_client()).tailor(master(), job, company, None)
    assert result.ats.passed
    assert {c.change for c in result.diff} <= {"rephrased"}  # only JD respellings
