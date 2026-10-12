"""Apollo.io ContactProvider (PLAN.md Phase 8): people search by company domain and titles.

**Written from Apollo's API docs, not yet verified against real responses** (no one in the group has
an Apollo account registered with a work email, which the free plan requires for search). It's only
used when a user saves an Apollo key; until then the contact waterfall is database → Hunter. Record
real responses with `record_sources.py apollo` once a key exists, and check the fixtures still match.

People search (`mixed_people/api_search`) costs no credits but returns no email addresses and only an
obfuscated last name; the best few people with `has_email` are then enriched one by one
(`people/match`, 1 credit each) to get their name and address. Apollo has no verifier, so addresses
are verified by the next provider in the waterfall (Hunter).
"""

import logging
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

BASE_URL = "https://api.apollo.io/api/v1"
DEFAULT_TITLES = [
    "founder",
    "co-founder",
    "cto",
    "engineering manager",
    "head of engineering",
    "technical recruiter",
    "talent acquisition",
]
SEARCH_SENIORITIES = ["founder", "c_suite", "vp", "head", "director", "manager", "senior"]
PER_PAGE = 25
MAX_ENRICH = 3  # credits spent per search, at most

# Apollo's email_status → ours. Anything not "verified" is checked by the verifier before use.
_STATUS = {"verified": VerificationStatus.VALID, "unavailable": VerificationStatus.INVALID}


def _status(value: Any) -> VerificationStatus | None:
    if not value:
        return None
    return _STATUS.get(str(value).lower(), VerificationStatus.UNKNOWN)


def _person(item: dict[str, Any]) -> PersonCandidate | None:
    email = item.get("email")
    if not email:
        return None
    first, last = item.get("first_name"), item.get("last_name")
    name = item.get("name") or " ".join(p for p in (first, last) if p) or email.split("@", 1)[0]
    departments = item.get("departments") or []
    return PersonCandidate(
        full_name=name,
        first_name=first,
        last_name=last,
        title=item.get("title"),
        department=departments[0] if departments else None,
        seniority=item.get("seniority"),
        email=str(email).lower(),
        verification=_status(item.get("email_status")),
        source=EmailSource.APOLLO,
    )


class ApolloProvider(ContactProvider):
    name = "apollo"
    can_verify = False

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "Sherlock/0.1 (self-hosted)",
        }
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            for attempt in (1, 2):  # one retry on network errors and 5xx
                try:
                    response = await client.request(method, f"{BASE_URL}/{path}", json=body, headers=headers)
                except httpx.TransportError as exc:
                    if attempt == 2:
                        raise ContactProviderError(f"apollo {path}: {exc}") from exc
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
            raise ContactProviderError(f"apollo {path}: non-JSON response ({response.status_code})") from exc
        if response.status_code < 400:
            return body
        detail = str(body.get("error") or body.get("message") or response.reason_phrase)
        message = f"apollo {path}: {response.status_code} {detail}"
        if response.status_code in (401, 403):  # 403: the key or plan can't use this endpoint
            raise ContactProviderAuthError(message)
        if response.status_code == 422 and "credit" in detail.lower():
            raise ContactQuotaError(message)
        raise ContactProviderError(message)

    async def search_people(
        self, *, domain: str | None = None, company: str | None = None, titles: list[str] | None = None
    ) -> PeopleSearch:
        if not domain:  # Apollo's people search filters by employer domain only
            return PeopleSearch(domain=None, organization=company)
        found = await self._call(
            "POST",
            "mixed_people/api_search",
            {
                "q_organization_domains_list": [domain],
                "person_titles": titles or DEFAULT_TITLES,
                "person_seniorities": SEARCH_SENIORITIES,
                "page": 1,
                "per_page": PER_PAGE,
            },
        )
        listed = [p for p in found.get("people") or [] if p.get("id") and p.get("has_email")]
        people: list[PersonCandidate] = []
        organization = None
        for item in listed[:MAX_ENRICH]:
            enriched = (await self._call("POST", "people/match", {"id": item["id"]})).get("person") or {}
            organization = organization or (enriched.get("organization") or {}).get("name")
            if person := _person({**item, **enriched}):
                people.append(person)
        return PeopleSearch(domain=domain, organization=organization or company, people=people)

    async def find_email(self, domain: str, first_name: str, last_name: str) -> EmailResult:
        body = {"first_name": first_name, "last_name": last_name, "domain": domain}
        person = (await self._call("POST", "people/match", body)).get("person") or {}
        email = person.get("email")
        return EmailResult(
            email=str(email).lower() if email else None,
            verification=_status(person.get("email_status")),
            source=EmailSource.APOLLO,
        )

    async def verify(self, email: str) -> VerificationStatus:
        raise ContactProviderError("Apollo has no email verifier; verify with Hunter")

    async def check_key(self) -> None:
        health = await self._call("GET", "auth/health")
        if not health.get("is_logged_in", True):
            raise ContactProviderAuthError("apollo: key not recognised")
