"""Record real LLM outputs for fixtures, for the FakeLLMClient to replay in tests.

Run from backend/ with a real GEMINI_API_KEY in .env (one fast-model request per item):
    uv run python -m tests.fixtures.record_llm            # resumes (parse_resume)
    uv run python -m tests.fixtures.record_llm hn         # HN thread fixture (parse_hn_comment)
    uv run python -m tests.fixtures.record_llm match      # matching fixture jobs (match)

Re-run whenever the corresponding prompt changes version.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.redis import get_redis
from app.schemas.resume import ParsedResume
from app.services.llm.gemini import GeminiClient
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.rate_limit import RateLimiter
from app.services.llm.redaction import redact_pii
from app.services.resume.parser import build_parse_prompt, extract_document, find_urls
from app.services.sources.hn import HNJob
from app.services.sources.text import html_to_text

FIXTURES = Path(__file__).parent
RESUMES = FIXTURES / "resumes"
RECORDED = FIXTURES / "llm" / "parse_resume"
FIXTURE_FILES = ["aarav_menon.pdf", "meera_iyer.pdf", "rohan_das.docx"]


def _client() -> GeminiClient:
    settings = get_settings()
    return GeminiClient(
        default_api_key=settings.gemini_api_key,
        model_smart=settings.llm_model_smart,
        model_fast=settings.llm_model_fast,
        limiter=RateLimiter(get_redis(), rpm=settings.llm_rpm, rpd=settings.llm_rpd),
    )


async def record_hn() -> None:
    thread = json.loads((FIXTURES / "sources" / "hn" / "thread.json").read_text())
    comments = [
        {"comment_id": c["id"], "text": redact_pii(html_to_text(c["text"]))[:4000]}
        for c in thread["children"]
    ]
    prompt = load_prompt("parse_hn_comment")
    request = prompt.request(tier="fast", comments=json.dumps(comments, ensure_ascii=False))
    request = type(request)(**{**request.__dict__, "use_cache": False})
    jobs = await _client().generate(request, list[HNJob])
    out = FIXTURES / "llm" / "parse_hn_comment" / "thread.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([j.model_dump() for j in jobs], indent=2) + "\n")
    print(f"recorded {out.relative_to(FIXTURES)} ({len(jobs)} jobs, prompt v{prompt.version})")


async def record_match() -> None:
    from app.services.matching.profile import candidate_payload
    from app.services.matching.rerank import Reranker, job_payload
    from tests.matching_fixtures import FIXTURE_PREFS, SCORED_KEYS, fixture_jobs, fixture_resume, unsaved_job

    candidate = candidate_payload(FIXTURE_PREFS, fixture_resume())
    jobs = [unsaved_job(item) for item in fixture_jobs() if item["key"] in SCORED_KEYS]
    scores = await Reranker(_client()).request_scores(
        candidate, [job_payload(job, company) for job, company in jobs], None
    )
    out = FIXTURES / "llm" / "match" / "fixture_jobs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([s.model_dump() for s in scores.values()], indent=2) + "\n")
    print(f"recorded {out.relative_to(FIXTURES)} ({len(scores)} of {len(jobs)} jobs scored)")


async def main() -> None:
    settings = get_settings()
    client = _client()
    prompt = load_prompt("parse_resume")
    RECORDED.mkdir(parents=True, exist_ok=True)
    for filename in FIXTURE_FILES:
        document = extract_document((RESUMES / filename).read_bytes(), filename)
        resume_text, links = build_parse_prompt(document, find_urls(document))
        request = prompt.request(tier="fast", resume_text=resume_text, links=links)
        request = type(request)(**{**request.__dict__, "use_cache": False})
        parsed = await client.generate(request, ParsedResume)
        out = RECORDED / f"{Path(filename).stem}.json"
        out.write_text(parsed.model_dump_json(indent=2) + "\n")
        print(f"recorded {out.relative_to(FIXTURES)} (prompt v{prompt.version}, {settings.llm_model_fast})")


if __name__ == "__main__":
    modes = {"hn": record_hn, "match": record_match}
    asyncio.run(modes[sys.argv[1]]() if sys.argv[1:] else main())
