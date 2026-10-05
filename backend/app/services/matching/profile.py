"""What matching knows about a user and a job: embedding texts and the condensed, PII-free resume sent
to the LLM (PLAN.md §3.1: no `basics`, emails and phone numbers scrubbed)."""

from typing import Any

from app.models import Job
from app.schemas.preferences import PreferencesBase
from app.schemas.resume import Bullet, MasterResume
from app.services.llm.redaction import redact_pii
from app.services.resume.skills import get_lexicon

JOB_DESCRIPTION_CHARS = 2000
PROFILE_BULLETS = 12


def job_text(job: Job) -> str:
    """Embedding and prompt text for a job: title + first 2k chars of the description."""
    return f"{job.title}\n{job.description_text[:JOB_DESCRIPTION_CHARS]}".strip()


def user_skills(resume: MasterResume) -> set[str]:
    """Canonical names of every skill the resume lists: skills section, project tech, bullet tags."""
    raw = [s for items in resume.skills.values() for s in items]
    raw += [t for p in resume.projects for t in p.tech]
    raw += [s for b in resume.all_bullets() for s in b.skills]
    return set(get_lexicon().normalize_all(raw))


def _profile_bullets(resume: MasterResume) -> list[Bullet]:
    """Pinned bullets first, then experience, projects and achievements in resume order."""
    ordered = [
        *(b for e in resume.experience for b in e.bullets),
        *(b for p in resume.projects for b in p.bullets),
        *resume.achievements,
    ]
    return [b for b in ordered if b.pinned] + [b for b in ordered if not b.pinned]


def profile_text(target_roles: list[str], resume: MasterResume) -> str:
    """Embedding text for a user: target roles + skills + selected bullet texts."""
    skills = sorted(user_skills(resume))
    bullets = [b.text for b in _profile_bullets(resume)[:PROFILE_BULLETS]]
    parts = [
        "Target roles: " + ", ".join(target_roles) if target_roles else "",
        "Skills: " + ", ".join(skills) if skills else "",
        *bullets,
    ]
    return redact_pii("\n".join(p for p in parts if p))


def _period(start: str | None, end: str | None) -> str | None:
    if not start and not end:
        return None
    return f"{start or '?'} to {end or '?'}"


def condensed_resume(resume: MasterResume) -> dict[str, Any]:
    """The resume as the scoring prompt sees it. No basics, no ids, PII scrubbed from free text."""
    r = redact_pii
    return {
        "summary": r(resume.summary) if resume.summary else None,
        "education": [
            {
                "institution": e.institution,
                "degree": " in ".join(x for x in (e.degree, e.field) if x) or None,
                "period": _period(e.start, e.end),
            }
            for e in resume.education
        ],
        "experience": [
            {
                "role": e.role,
                "org": e.org,
                "period": _period(e.start, e.end),
                "bullets": [r(b.text) for b in e.bullets],
            }
            for e in resume.experience
        ],
        "projects": [
            {"name": p.name, "tech": p.tech, "bullets": [r(b.text) for b in p.bullets]}
            for p in resume.projects
        ],
        "achievements": [r(b.text) for b in resume.achievements],
    }


def candidate_payload(prefs: PreferencesBase, resume: MasterResume) -> dict[str, Any]:
    """The `candidate` block of prompts/match.md."""
    return {
        "target_roles": prefs.target_roles,
        "employment_types": prefs.employment_types,
        "locations": prefs.locations,
        "remote_ok": prefs.remote_ok,
        "skills": sorted(user_skills(resume)),
        "resume": condensed_resume(resume),
    }
