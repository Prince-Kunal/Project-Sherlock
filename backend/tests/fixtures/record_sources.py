"""Record real job-source responses as fixtures (trimmed to a few jobs). Run from backend/:
    uv run python -m tests.fixtures.record_sources

Adapters are coded against these fixtures (PLAN.md Phase 2): re-record when an API's shape changes.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

OUT = Path(__file__).parent / "sources"
HEADERS = {"User-Agent": "Sherlock/0.1 (job discovery; self-hosted)"}


def save(name: str, data: Any) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("recorded", path.relative_to(OUT.parent))


def main() -> None:
    c = httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True)

    gh = c.get("https://boards-api.greenhouse.io/v1/boards/figma/jobs", params={"content": "true"}).json()
    gh["jobs"] = gh["jobs"][:3]
    save("greenhouse/board_figma.json", gh)
    time.sleep(1)
    job_id = gh["jobs"][0]["id"]
    save(
        "greenhouse/job_figma.json",
        c.get(f"https://boards-api.greenhouse.io/v1/boards/figma/jobs/{job_id}").json(),
    )

    lever = c.get("https://api.lever.co/v0/postings/cred", params={"mode": "json"}).json()[:3]
    save("lever/board_cred.json", lever)
    time.sleep(1)
    save(
        "lever/job_cred.json",
        c.get(f"https://api.lever.co/v0/postings/cred/{lever[0]['id']}", params={"mode": "json"}).json(),
    )

    ashby = c.get("https://api.ashbyhq.com/posting-api/job-board/sarvam").json()
    ashby["jobs"] = ashby["jobs"][:3]
    save("ashby/board_sarvam.json", ashby)

    search = c.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={"tags": "story,author_whoishiring", "hitsPerPage": 4},
    ).json()
    search["hits"] = [
        {k: h[k] for k in ("objectID", "title", "created_at", "author")} for h in search["hits"]
    ]
    save("hn/search.json", search)
    thread_id = next(h["objectID"] for h in search["hits"] if "Who is hiring" in h["title"])
    item = c.get(f"https://hn.algolia.com/api/v1/items/{thread_id}").json()
    # Keep a handful of top-level comments: some remote, some not; drop nested replies.
    remote = [ch for ch in item["children"] if "remote" in (ch.get("text") or "").lower()][:4]
    other = [ch for ch in item["children"] if ch not in remote and ch.get("text")][:2]
    item["children"] = [{**ch, "children": []} for ch in remote + other]
    save("hn/thread.json", item)


def record_adzuna() -> None:
    """Needs ADZUNA_APP_ID/ADZUNA_APP_KEY in the environment. The app id is scrubbed from the fixture."""
    app_id, app_key = os.environ["ADZUNA_APP_ID"], os.environ["ADZUNA_APP_KEY"]
    data = httpx.get(
        "https://api.adzuna.com/v1/api/jobs/in/search/1",
        params={
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 4,
            "what": "software engineer intern",
            "max_days_old": 14,
            "sort_by": "date",
            "content-type": "application/json",
        },
        headers=HEADERS,
        timeout=30,
    ).json()
    for r in data["results"]:
        r.pop("adref", None)
        r["redirect_url"] = re.sub(r"utm_source=[^&]+", "utm_source=APP_ID", r["redirect_url"])
    text = json.dumps(data)
    if app_id in text or app_key in text:
        raise SystemExit("Adzuna credentials leaked into the fixture; not saving")
    save("adzuna/search_in.json", data)


_FAKE_PEOPLE = [("Asha", "Rao"), ("Vikram", "Iyer"), ("Neha", "Kapoor"), ("Rahul", "Menon"), ("Divya", "Shah"),
                ("Arjun", "Pillai"), ("Kavya", "Reddy"), ("Rohit", "Bose"), ("Meera", "Joshi"), ("Karan", "Gill")]  # fmt: skip


def _anonymise_person(item: dict[str, Any], i: int, domain: str) -> dict[str, Any]:
    """Real people's names and addresses never go into the repo: keep the shape, invent the person."""
    first, last = _FAKE_PEOPLE[i % len(_FAKE_PEOPLE)]
    item.update(first_name=first, last_name=last, value=f"{first.lower()}.{last.lower()}@{domain}")
    for key in ("linkedin", "linkedin_url", "twitter", "phone_number"):
        if key in item:
            item[key] = None
    item["sources"] = [
        {**src, "uri": f"https://{domain}/", "domain": domain} for src in (item.get("sources") or [])[:1]
    ]
    return item


def record_hunter() -> None:
    """Needs HUNTER_API_KEY. Costs ~1 search + 1 email-finder + 1 verification credit."""
    key = os.environ["HUNTER_API_KEY"]
    c = httpx.Client(timeout=30, headers={**HEADERS, "X-API-KEY": key})
    base = "https://api.hunter.io/v2"
    domain = "sarvam.ai"
    search = c.get(
        f"{base}/domain-search",
        params={
            "domain": domain,
            "type": "personal",
            "seniority": "senior,executive",
            "department": "executive,it,management,hr",
            "limit": 10,
        },
    ).json()
    if "errors" in search:
        raise SystemExit(f"Hunter error: {search['errors']}")
    real = dict(search["data"]["emails"][0])  # copy: anonymising edits the results in place
    search["data"]["emails"] = [
        _anonymise_person(e, i, domain) for i, e in enumerate(search["data"]["emails"])
    ]

    finder = c.get(
        f"{base}/email-finder",
        params={"domain": domain, "first_name": real["first_name"], "last_name": real["last_name"]},
    ).json()
    if "data" in finder:
        finder["data"] = _anonymise_person(
            {**finder["data"], "value": finder["data"].get("email")}, 0, domain
        )
        finder["data"]["email"] = finder["data"].pop("value")
        finder["meta"]["params"].update(first_name="Asha", last_name="Rao")

    verify = c.get(f"{base}/email-verifier", params={"email": f"careers@{domain}"}).json()
    text = json.dumps([search, finder, verify])
    leaks = [key, real["value"], real["first_name"], real["last_name"]]
    if any(s and s in text for s in leaks):
        raise SystemExit("a key or a real person leaked into the fixtures; nothing saved")
    save("hunter/domain_search.json", search)
    save("hunter/email_finder.json", finder)
    save("hunter/email_verifier.json", verify)
    account = c.get(f"{base}/account").json()["data"]["requests"]
    print("credits after recording:", account)


def _scrub(value: Any, swaps: dict[str, str]) -> Any:
    """Replace real addresses and names everywhere, including inside base64url message bodies."""
    import base64

    def text(t: str) -> str:
        for real, fake in swaps.items():
            t = re.sub(re.escape(real), fake, t, flags=re.IGNORECASE)
        return t

    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "data" and isinstance(v, str):
                decoded = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4)).decode("utf-8", "replace")
                out[k] = base64.urlsafe_b64encode(text(decoded).encode()).decode().rstrip("=")
            else:
                out[k] = _scrub(v, swaps)
        return out
    if isinstance(value, list):
        return [_scrub(v, swaps) for v in value]
    return text(value) if isinstance(value, str) else value


def record_gmail() -> None:
    """A real Gmail thread as a fixture, anonymised (PLAN.md Phase 7 manual test, docs/MANUAL_TESTS.md).

        uv run python -m tests.fixtures.record_sources gmail <outreach_id> <fixture_name>

    Reads the outreach's owner and thread from the app database and calls Gmail with their stored
    authorisation (needs DATABASE_URL, FERNET_KEY, GOOGLE_CLIENT_ID/SECRET). Addresses and names of
    both people are replaced with the fixture persons'; attachments aren't downloaded."""
    import asyncio
    import uuid

    from app.core.db import get_sessionmaker
    from app.core.redis import get_redis
    from app.models import Contact, Outreach, User
    from app.services.email.connection import GmailAccess
    from app.services.registry import get_google_oauth

    outreach_id, name = uuid.UUID(sys.argv[2]), sys.argv[3]

    async def run() -> None:
        async with get_sessionmaker()() as session:
            outreach = await session.get(Outreach, outreach_id)
            if outreach is None or outreach.gmail_thread_id is None:
                raise SystemExit("no sent outreach with that id")
            user = await session.get(User, outreach.user_id)
            contact = await session.get(Contact, outreach.contact_id) if outreach.contact_id else None
            oauth = get_google_oauth()
            if user is None or contact is None or oauth is None:
                raise SystemExit("missing user, contact or Google OAuth settings")
            client = await GmailAccess(oauth, get_redis())(session, user)
            data = await client._request(
                "GET", f"threads/{outreach.gmail_thread_id}", params={"format": "full"}
            )  # type: ignore[attr-defined]
        swaps = {
            user.email: "rohan.das.dev@gmail.com",
            contact.email: "priya@ledgerline.example",
            contact.full_name: "Priya Nair",
            user.name: "Rohan Das",
        }
        scrubbed = _scrub(data, {k: v for k, v in swaps.items() if k})
        text = json.dumps(scrubbed)
        if any(k and k.lower() in text.lower() for k in swaps if "@" in k):
            raise SystemExit("a real address survived the scrub; nothing saved")
        save(f"gmail/{name}.json", scrubbed)

    asyncio.run(run())


YC_FIELDS = (
    "name", "slug", "website", "one_liner", "long_description", "team_size", "industry", "subindustry",
    "industries", "tags", "regions", "all_locations", "status", "stage", "isHiring", "nonprofit",
)  # fmt: skip


def record_yc() -> None:
    """A slice of the public YC directory (company data only, no people): small and mid-size Indian
    companies, remote-first ones, US-only ones, an inactive one and one without a website."""
    from app.services.prospects.yc import YC_DIRECTORY_URL

    data = httpx.Client(timeout=120, headers=HEADERS).get(YC_DIRECTORY_URL).json()
    by_slug = sorted(data, key=lambda c: c["slug"])

    def pick(test: Any, n: int) -> list[dict[str, Any]]:
        return [c for c in by_slug if test(c)][:n]

    def india(c: dict[str, Any]) -> bool:
        return "India" in (c.get("regions") or [])

    active = [c for c in by_slug if c.get("status") == "Active" and c.get("website")]
    chosen = (
        pick(lambda c: c in active and india(c) and (c.get("team_size") or 0) <= 50, 4)
        + pick(lambda c: c in active and india(c) and 50 < (c.get("team_size") or 0) <= 500, 2)
        + pick(lambda c: c in active and "Fully Remote" in c["regions"] and not india(c), 3)
        + pick(lambda c: c in active and c["regions"] == ["United States of America", "America / Canada"], 2)
        + pick(lambda c: c.get("status") == "Inactive" and india(c), 1)
        + pick(lambda c: not c.get("website") and c.get("status") == "Active", 1)
    )
    save("yc/companies.json", [{k: c.get(k) for k in YC_FIELDS} for c in chosen])


if __name__ == "__main__":
    modes = {"adzuna": record_adzuna, "hunter": record_hunter, "gmail": record_gmail, "yc": record_yc}
    modes.get(sys.argv[1] if sys.argv[1:] else "", main)()
