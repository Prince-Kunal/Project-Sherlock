"""Gmail interface and the real client (PLAN.md Phase 7): send with `users.messages.send`, read
threads with `users.threads.get`. Called over REST with httpx (async; the official client library's
transport is synchronous). Bound to one user's mailbox; access tokens come from `token_source`.
"""

import base64
import html
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

API = "https://gmail.googleapis.com/gmail/v1/users/me"


class Attachment(BaseModel):
    filename: str
    content_type: str = "application/pdf"
    data: bytes


class OutgoingEmail(BaseModel):
    to: str
    subject: str
    body: str  # plain text
    attachment: Attachment | None = None
    # Follow-ups reply in-thread with no attachment.
    thread_id: str | None = None
    in_reply_to: str | None = None  # the RFC 822 Message-ID being answered


class SentMessage(BaseModel):
    message_id: str
    thread_id: str


class ThreadMessage(BaseModel):
    message_id: str
    from_address: str
    to_address: str
    subject: str
    body: str
    sent_at: datetime
    rfc_message_id: str | None = None
    snippet: str = ""
    auto_submitted: bool = False  # out-of-office and other automatic replies


class GmailError(Exception):
    """Gmail refused the request or failed."""


class GmailNotConnectedError(GmailError):
    """The user has no usable Gmail authorisation (never connected, or it expired)."""


class GmailClient(ABC):
    """Bound to one user's mailbox."""

    @abstractmethod
    async def send(self, message: OutgoingEmail) -> SentMessage: ...

    @abstractmethod
    async def get_thread(self, thread_id: str) -> list[ThreadMessage]: ...


def build_mime(message: OutgoingEmail, sender_email: str, sender_name: str) -> EmailMessage:
    mime = EmailMessage()
    mime["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Message-ID"] = make_msgid(domain=sender_email.rsplit("@", 1)[-1])
    if message.in_reply_to:
        mime["In-Reply-To"] = message.in_reply_to
        mime["References"] = message.in_reply_to
    mime.set_content(message.body, charset="utf-8")
    if message.attachment is not None:
        maintype, _, subtype = message.attachment.content_type.partition("/")
        mime.add_attachment(
            message.attachment.data, maintype=maintype, subtype=subtype, filename=message.attachment.filename
        )
    return mime


def _b64decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _find_part(payload: dict[str, Any], mime_type: str) -> str | None:
    if payload.get("mimeType") == mime_type and (data := payload.get("body", {}).get("data")):
        return _b64decode(data)
    for part in payload.get("parts", []) or []:
        if part.get("filename"):
            continue  # an attachment
        if (found := _find_part(part, mime_type)) is not None:
            return found
    return None


def _html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>|<br\s*/?>|</p>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def parse_thread(data: dict[str, Any]) -> list[ThreadMessage]:
    """A `users.threads.get?format=full` response as messages, oldest first."""
    messages = []
    for item in data.get("messages", []):
        payload = item.get("payload", {})
        headers = _headers(payload)
        body = _find_part(payload, "text/plain")
        if body is None:
            body = _html_to_text(_find_part(payload, "text/html") or "")
        auto = headers.get("auto-submitted", "no").lower() not in ("", "no") or bool(
            re.match(
                r"(?i)(automatic reply|auto(matic)?[- ]?reply|out of (the )?office)",
                headers.get("subject", ""),
            )
        )
        messages.append(
            ThreadMessage(
                message_id=item["id"],
                from_address=parseaddr(headers.get("from", ""))[1].lower(),
                to_address=parseaddr(headers.get("to", ""))[1].lower(),
                subject=headers.get("subject", ""),
                body=body,
                sent_at=datetime.fromtimestamp(int(item.get("internalDate", "0")) / 1000, tz=UTC),
                rfc_message_id=headers.get("message-id"),
                snippet=html.unescape(item.get("snippet", "")),
                auto_submitted=auto,
            )
        )
    return sorted(messages, key=lambda m: m.sent_at)


TokenSource = Callable[[bool], Awaitable[str]]  # force_refresh → access token


class GmailApiClient(GmailClient):
    def __init__(
        self,
        token_source: TokenSource,
        sender_email: str,
        sender_name: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token_source
        self._email = sender_email
        self._name = sender_name
        self._client = client

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            for attempt in (1, 2):  # a 401 means the cached access token went stale: refresh once
                token = await self._token(attempt == 2)
                try:
                    response = await client.request(
                        method, f"{API}/{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
                    )
                except httpx.TransportError as exc:
                    raise GmailError(f"gmail {path}: {exc}") from exc
                if response.status_code == 401 and attempt == 1:
                    continue
                if response.status_code >= 400:
                    try:
                        error = response.json().get("error", {})
                        detail = f"{error.get('status', '')} {error.get('message', '')}".strip()
                    except ValueError:
                        detail = response.text[:200]
                    raise GmailError(f"gmail {path}: {response.status_code} {detail}")
                result: dict[str, Any] = response.json()
                return result
        finally:
            if self._client is None:
                await client.aclose()
        raise AssertionError("unreachable")

    async def send(self, message: OutgoingEmail) -> SentMessage:
        raw = base64.urlsafe_b64encode(build_mime(message, self._email, self._name).as_bytes()).decode()
        body: dict[str, Any] = {"raw": raw}
        if message.thread_id:
            body["threadId"] = message.thread_id
        data = await self._request("POST", "messages/send", json=body)
        return SentMessage(message_id=data["id"], thread_id=data["threadId"])

    async def get_thread(self, thread_id: str) -> list[ThreadMessage]:
        return parse_thread(await self._request("GET", f"threads/{thread_id}", params={"format": "full"}))
