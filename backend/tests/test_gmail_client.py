"""Phase 7: the real Gmail client over REST (respx): the MIME it sends, follow-ups in the same
thread, the stale-token retry, errors, and reading a thread."""

import base64
import email
import json
from email import policy

import httpx
import pytest
import respx

from app.services.email.gmail import API, Attachment, GmailApiClient, GmailError, OutgoingEmail
from tests.conftest import FIXTURES


def _client(tokens: list[bool]) -> GmailApiClient:
    async def token_source(force_refresh: bool) -> str:
        tokens.append(force_refresh)
        return "fresh" if force_refresh else "cached"

    return GmailApiClient(token_source, "rohan.das.dev@gmail.com", "Rohan Das")


def _sent_mime(route: respx.Route) -> tuple[dict[str, object], email.message.EmailMessage]:
    body = json.loads(route.calls.last.request.content)
    raw = base64.urlsafe_b64decode(body["raw"])
    return body, email.message_from_bytes(raw, policy=policy.default)  # type: ignore[return-value]


@respx.mock
async def test_send_builds_a_plain_text_email_with_the_pdf() -> None:
    route = respx.post(f"{API}/messages/send").mock(
        return_value=httpx.Response(200, json={"id": "m1", "threadId": "t1", "labelIds": ["SENT"]})
    )
    sent = await _client([]).send(
        OutgoingEmail(
            to="priya@ledgerline.example",
            subject="Backend intern role at Ledgerline",
            body="Hi Priya,\n\nWould you refer me? Resume's attached.",
            attachment=Attachment(filename="Rohan_Das_Resume.pdf", data=b"%PDF-1.7 x"),
        )
    )
    assert (sent.message_id, sent.thread_id) == ("m1", "t1")
    body, mime = _sent_mime(route)
    assert "threadId" not in body
    assert mime["From"] == "Rohan Das <rohan.das.dev@gmail.com>"
    assert mime["To"] == "priya@ledgerline.example"
    assert mime["Subject"] == "Backend intern role at Ledgerline"
    assert mime["Message-ID"].endswith("@gmail.com>")
    text = mime.get_body(("plain",))
    assert text is not None
    assert "Would you refer me?" in text.get_content()
    [pdf] = list(mime.iter_attachments())
    assert pdf.get_filename() == "Rohan_Das_Resume.pdf"
    assert pdf.get_content_type() == "application/pdf"
    assert pdf.get_content() == b"%PDF-1.7 x"
    assert route.calls.last.request.headers["Authorization"] == "Bearer cached"


@respx.mock
async def test_a_follow_up_replies_in_the_thread() -> None:
    route = respx.post(f"{API}/messages/send").mock(
        return_value=httpx.Response(200, json={"id": "m2", "threadId": "t1"})
    )
    await _client([]).send(
        OutgoingEmail(
            to="priya@ledgerline.example",
            subject="Re: Backend intern role at Ledgerline",
            body="Following up.",
            thread_id="t1",
            in_reply_to="<172839.1@gmail.com>",
        )
    )
    body, mime = _sent_mime(route)
    assert body["threadId"] == "t1"
    assert mime["In-Reply-To"] == "<172839.1@gmail.com>"
    assert mime["References"] == "<172839.1@gmail.com>"
    assert list(mime.iter_attachments()) == []


@respx.mock
async def test_a_stale_access_token_is_refreshed_once() -> None:
    respx.post(f"{API}/messages/send").mock(
        side_effect=[
            httpx.Response(401, json={"error": {"code": 401, "status": "UNAUTHENTICATED"}}),
            httpx.Response(200, json={"id": "m1", "threadId": "t1"}),
        ]
    )
    tokens: list[bool] = []
    await _client(tokens).send(OutgoingEmail(to="a@b.example", subject="s", body="b"))
    assert tokens == [False, True]


@respx.mock
async def test_gmail_errors_are_raised_with_the_reason() -> None:
    respx.post(f"{API}/messages/send").mock(
        return_value=httpx.Response(
            400, json={"error": {"code": 400, "message": "Invalid To header", "status": "INVALID_ARGUMENT"}}
        )
    )
    with pytest.raises(GmailError, match="Invalid To header"):
        await _client([]).send(OutgoingEmail(to="nope", subject="s", body="b"))


@respx.mock
async def test_reading_a_thread() -> None:
    data = json.loads((FIXTURES / "sources" / "gmail" / "thread_reply.json").read_text())
    route = respx.get(f"{API}/threads/18f2a0c0d1e2f300").mock(return_value=httpx.Response(200, json=data))
    messages = await _client([]).get_thread("18f2a0c0d1e2f300")
    assert [m.from_address for m in messages] == ["rohan.das.dev@gmail.com", "priya@ledgerline.example"]
    assert route.calls.last.request.url.params["format"] == "full"


def test_the_recorder_scrubs_addresses_inside_encoded_bodies() -> None:
    from tests.fixtures.record_sources import _scrub

    body = base64.urlsafe_b64encode(b"Hi Real Person, write to me at real.me@gmail.com").decode().rstrip("=")
    data = {
        "payload": {
            "headers": [{"name": "From", "value": "Real Me <REAL.ME@gmail.com>"}],
            "body": {"data": body},
        }
    }
    scrubbed = _scrub(data, {"real.me@gmail.com": "rohan.das.dev@gmail.com", "Real Person": "Priya Nair"})
    assert scrubbed["payload"]["headers"][0]["value"] == "Real Me <rohan.das.dev@gmail.com>"
    decoded = base64.urlsafe_b64decode(scrubbed["payload"]["body"]["data"] + "==").decode()
    assert decoded == "Hi Priya Nair, write to me at rohan.das.dev@gmail.com"
