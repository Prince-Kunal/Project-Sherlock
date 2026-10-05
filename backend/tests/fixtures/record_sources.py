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


if __name__ == "__main__":
    record_adzuna() if sys.argv[1:] == ["adzuna"] else main()
