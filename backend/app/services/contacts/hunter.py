"""Hunter.io ContactProvider (PLAN.md Phase 5): domain search, email finder, email verifier.

The key goes in the X-API-KEY header (never the URL, so it can't leak into logs). Each user brings
their own key; Hunter's free plan is per account.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.models.enums import EmailSource, VerificationStatus
from app.services.contacts.base import (
    ContactProvider,
    ContactProviderAuthError,
    ContactProviderError,
    ContactQuotaError,
    EmailResult,
    PeopleSearch,
    PersonCandidate,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.hunter.io/v2"
# Who might refer a student: leadership, engineering, people/HR. Hunter filters by these, not titles.
SEARCH_SENIORITY = "senior,executive"
SEARCH_DEPARTMENTS = "executive,it,management,hr"
SEARCH_LIMIT = 10

_STATUS = {
    "valid": VerificationStatus.VALID,
    "invalid": VerificationStatus.INVALID,
    "accept_all": VerificationStatus.ACCEPT_ALL,
    "unknown": VerificationStatus.UNKNOWN,
    "disposable": VerificationStatus.INVALID,
}


def map_status(status: str | None, result: str | None = None) -> VerificationStatus | None:
    """Hunter verification status → ours. "webmail" (e.g. a gmail address) has no status of its own:
    its `result` decides (deliverable → valid, risky → accept_all, undeliverable → invalid)."""
    if not status:
        return None
    if status == "webmail":
        return {
            "deliverable": VerificationStatus.VALID,
            "risky": VerificationStatus.ACCEPT_ALL,
            "undeliverable": VerificationStatus.INVALID,
        }.get(result or "", VerificationStatus.UNKNOWN)
    return _STATUS.get(status, VerificationStatus.UNKNOWN)


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _person(item: dict[str, Any]) -> PersonCandidate | None:
    email = item.get("value")
    if not email:
        return None
    first, last = item.get("first_name"), item.get("last_name")
    name = " ".join(p for p in (first, last) if p) or email.split("@", 1)[0]
    verification = item.get("verification") or {}
    return PersonCandidate(
        full_name=name,
        first_name=first,
        last_name=last,
        title=item.get("position"),
        department=item.get("department"),
        seniority=item.get("seniority"),
        email=email.lower(),
        confidence=item.get("confidence"),
        verification=map_status(verification.get("status")),
        verified_at=_date(verification.get("date")),
        source=EmailSource.HUNTER,
    )


class HunterProvider(ContactProvider):
    name = "hunter"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"X-API-KEY": self._api_key, "User-Agent": "Sherlock/0.1 (self-hosted)"}
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            for attempt in (1, 2):  # one retry on network errors and 5xx
                try:
                    response = await client.get(f"{BASE_URL}/{path}", params=params, headers=headers)
                except httpx.TransportError as exc:
                    if attempt == 2:
                        raise ContactProviderError(f"hunter {path}: {exc}") from exc
                    continue
                if response.status_code >= 500 and attempt == 1:
                    continue
                return self._parse(path, response)
        finally:
            if self._client is None:
                await client.aclose()
        raise AssertionError("unreachable")

    @staticmethod
    def _parse(path: str, response: httpx.Response) -> dict[str, Any]:
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ContactProviderError(f"hunter {path}: non-JSON response ({response.status_code})") from exc
        if response.status_code < 400:
            return body
        errors = body.get("errors") or [{}]
        error_id = str(errors[0].get("id") or "")
        details = str(errors[0].get("details") or response.reason_phrase)
        message = f"hunter {path}: {response.status_code} {error_id} {details}".strip()
        if response.status_code in (401, 403) or error_id in {"authentication_failed", "restricted_account"}:
            raise ContactProviderAuthError(message)
        if (response.status_code == 429 and error_id in {"usage_exceeded", "too_many_requests"}) or (
            response.status_code == 429 and "credit" in details.lower()
        ):
            raise ContactQuotaError(message)
        raise ContactProviderError(message)

    async def search_people(self, *, domain: str | None = None, company: str | None = None) -> PeopleSearch:
        if not domain and not company:
            raise ValueError("search_people needs a domain or a company name")
        params: dict[str, Any] = {
            "type": "personal",
            "seniority": SEARCH_SENIORITY,
            "department": SEARCH_DEPARTMENTS,
            "limit": SEARCH_LIMIT,
        }
        params["domain" if domain else "company"] = domain or company
        data = (await self._get("domain-search", params)).get("data") or {}
        people = [p for p in (_person(e) for e in data.get("emails") or []) if p]
        return PeopleSearch(
            domain=(data.get("domain") or domain or None),
            organization=data.get("organization"),
            headcount=data.get("headcount"),
            people=people,
        )

    async def find_email(self, domain: str, first_name: str, last_name: str) -> EmailResult:
        params = {"domain": domain, "first_name": first_name, "last_name": last_name}
        data = (await self._get("email-finder", params)).get("data") or {}
        verification = data.get("verification") or {}
        email = data.get("email")
        return EmailResult(
            email=email.lower() if email else None,
            confidence=data.get("score"),
            verification=map_status(verification.get("status")),
            source=EmailSource.HUNTER,
        )

    async def verify(self, email: str) -> VerificationStatus:
        data = (await self._get("email-verifier", {"email": email})).get("data") or {}
        return map_status(data.get("status"), data.get("result")) or VerificationStatus.UNKNOWN

    async def check_key(self) -> None:
        await self._get("account")
