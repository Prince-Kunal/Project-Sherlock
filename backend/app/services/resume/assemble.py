"""Turning a validated TailorPlan into a tailored resume (PLAN.md Phase 4). Pure functions plus the
one-page render loop; everything here only selects, reorders or respells what the master has."""

import asyncio
import io
import math
import re
from dataclasses import dataclass, field

import pdfplumber

from app.schemas.resume import Bullet, MasterResume
from app.schemas.tailor import ResumeChange, SectionKey, TailorPlan
from app.services.resume.render import RenderedResume, render_resume
from app.services.resume.skills import AMBIGUOUS_SKILLS, SkillLexicon, replace_skill_spelling
from app.services.resume.validator import master_skill_set

ALL_SECTIONS: list[SectionKey] = ["education", "experience", "projects", "skills", "achievements"]
MAX_RENDER_ATTEMPTS = 3
CHARS_PER_LINE = 100  # a conservative estimate for the template's A4 body text


@dataclass
class TailoredDraft:
    resume: MasterResume  # basics included (they never go to the LLM)
    section_order: list[SectionKey]
    ranking: list[str]  # selected bullet ids, most relevant first
    pinned: set[str] = field(default_factory=set)


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def apply_plan(master: MasterResume, plan: TailorPlan, lexicon: SkillLexicon) -> TailoredDraft:
    """Build the tailored resume from a plan that passed `validate_plan`.

    Education entries are always kept; experience keeps its chronological order; projects are ordered
    by their most relevant selected bullet and dropped when none of their bullets is selected."""
    known = {b.id for b in master.all_bullets()}
    ranking = [b for b in _dedupe(plan.selected_bullet_ids) if b in known]
    rank = {bullet_id: i for i, bullet_id in enumerate(ranking)}
    texts = plan.rephrasing_map()

    def pick(bullets: list[Bullet]) -> list[Bullet]:
        chosen = sorted((b for b in bullets if b.id in rank), key=lambda b: rank[b.id])
        return [b.model_copy(update={"text": texts.get(b.id, b.text)}) for b in chosen]

    education = [e.model_copy(update={"bullets": pick(e.bullets)}) for e in master.education]
    experience = [
        e.model_copy(update={"bullets": pick(e.bullets)})
        for e in master.experience
        if not e.bullets or any(b.id in rank for b in e.bullets)
    ]
    projects = sorted(
        (
            p.model_copy(update={"bullets": pick(p.bullets)})
            for p in master.projects
            if any(b.id in rank for b in p.bullets)
        ),
        key=lambda p: min(rank[b.id] for b in p.bullets),
    )

    order: list[SectionKey] = list(dict.fromkeys(s for s in plan.section_order if s in ALL_SECTIONS))
    if master.education and "education" not in order:
        order.insert(0, "education")  # a student's resume always shows education

    return TailoredDraft(
        resume=master.model_copy(
            update={
                "summary": plan.summary if (plan.summary and master.summary) else master.summary,
                "education": education,
                "experience": experience,
                "projects": projects,
                "skills": _shown_skills(master, plan.skills_to_show, lexicon),
                "achievements": pick(master.achievements),
            }
        ),
        section_order=order,
        ranking=ranking,
        pinned={b.id for b in master.all_bullets() if b.pinned},
    )


def _shown_skills(master: MasterResume, show: list[str], lexicon: SkillLexicon) -> dict[str, list[str]]:
    """The master's skill categories, filtered to `show` (canonical match) and ordered by it. An empty
    `show` keeps every skill."""
    if not show:
        return {k: list(v) for k, v in master.skills.items() if v}
    position = {name: i for i, name in enumerate(lexicon.normalize_all(show))}
    shown: dict[str, list[str]] = {}
    for category, items in master.skills.items():
        kept = sorted(
            (item for item in items if lexicon.normalize(item) in position),
            key=lambda item: position[lexicon.normalize(item)],
        )
        if kept:
            shown[category] = kept
    return dict(sorted(shown.items(), key=lambda kv: min(position[lexicon.normalize(i)] for i in kv[1])))


# --- §6.1 keyword rule -----------------------------------------------------------------------------


def jd_must_haves(jd_text: str, llm_keywords: list[str], lexicon: SkillLexicon) -> list[str]:
    """The JD's must-have keywords, spelled as in the JD. The LLM's list is kept only where it appears
    verbatim in the JD; without one, every known skill the JD mentions is used."""
    keywords: list[str] = []
    for keyword in llm_keywords:
        match = re.search(rf"(?<![\w+#.]){re.escape(keyword.strip())}(?![\w+#])", jd_text, re.IGNORECASE)
        if keyword.strip() and match:
            keywords.append(match.group(0))
    if not keywords:
        # Fallback scan. Skill names that are also words ("Go further") are too unreliable here.
        for spellings in lexicon.find_in_text(jd_text).values():
            clear = sorted(s for s in spellings if s.lower() not in AMBIGUOUS_SKILLS)
            keywords += clear[:1]
    seen: set[str] = set()
    unique: list[str] = []
    for keyword in keywords:
        key = lexicon.normalize(keyword)
        if key not in seen:
            seen.add(key)
            unique.append(keyword)
    return unique


def apply_jd_spelling(
    draft: TailoredDraft, must_haves: list[str], master: MasterResume, lexicon: SkillLexicon
) -> dict[str, str]:
    """Use the JD's spelling for skills the user already has (JD "PostgreSQL", master "postgres").
    Only aliases of skills in the master are swapped, so nothing new can appear. Returns the swaps
    made (canonical → JD spelling); `draft` is updated in place."""
    have = master_skill_set(master, lexicon)
    swaps = {
        lexicon.normalize(k): k for k in must_haves if lexicon.is_known(k) and lexicon.normalize(k) in have
    }
    if not swaps:
        return {}

    def respell_item(item: str) -> str:
        return swaps.get(lexicon.normalize(item), item)

    def respell_text(text: str) -> str:
        for canonical, spelling in swaps.items():
            # Skip aliases that are also words: "go" → "Go" would change "go live".
            aliases = [a for a in lexicon.aliases(canonical) if a not in AMBIGUOUS_SKILLS]
            text = replace_skill_spelling(text, aliases, spelling)
        return text

    def respell_bullets(bullets: list[Bullet]) -> list[Bullet]:
        return [b.model_copy(update={"text": respell_text(b.text)}) for b in bullets]

    r = draft.resume
    draft.resume = r.model_copy(
        update={
            "summary": respell_text(r.summary) if r.summary else None,
            "skills": {c: _dedupe([respell_item(i) for i in items]) for c, items in r.skills.items()},
            "education": [e.model_copy(update={"bullets": respell_bullets(e.bullets)}) for e in r.education],
            "experience": [
                e.model_copy(update={"bullets": respell_bullets(e.bullets)}) for e in r.experience
            ],
            "projects": [
                p.model_copy(
                    update={
                        "tech": _dedupe([respell_item(t) for t in p.tech]),
                        "bullets": respell_bullets(p.bullets),
                    }
                )
                for p in r.projects
            ],
            "achievements": respell_bullets(r.achievements),
        }
    )
    return swaps


# --- one page --------------------------------------------------------------------------------------


class PageOverflowError(Exception):
    def __init__(self, pages: int) -> None:
        super().__init__(f"still {pages} pages after {MAX_RENDER_ATTEMPTS} attempts")
        self.pages = pages


def overflow(pdf: bytes) -> tuple[int, int]:
    """(page count, text lines beyond the first page)."""
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        extra = sum(len((page.extract_text() or "").splitlines()) for page in doc.pages[1:])
        return len(doc.pages), extra


def _estimated_lines(bullet: Bullet) -> int:
    return max(1, math.ceil(len(bullet.text) / CHARS_PER_LINE))


def drop_lowest_ranked(draft: TailoredDraft, lines_needed: int) -> list[str]:
    """Remove the lowest-ranked non-pinned bullets until about `lines_needed` lines are freed. A project
    or achievement left with no bullets disappears with its header. Returns the dropped ids."""
    bullets = {b.id: b for b in draft.resume.all_bullets()}
    dropped: list[str] = []
    freed = 0
    for bullet_id in reversed(draft.ranking):
        if freed >= lines_needed:
            break
        if bullet_id in draft.pinned or bullet_id not in bullets:
            continue
        dropped.append(bullet_id)
        freed += _estimated_lines(bullets[bullet_id])
    if not dropped:
        return []
    gone = set(dropped)

    def keep(items: list[Bullet]) -> list[Bullet]:
        return [b for b in items if b.id not in gone]

    r = draft.resume
    draft.resume = r.model_copy(
        update={
            "education": [e.model_copy(update={"bullets": keep(e.bullets)}) for e in r.education],
            "experience": [e.model_copy(update={"bullets": keep(e.bullets)}) for e in r.experience],
            "projects": [
                p.model_copy(update={"bullets": keep(p.bullets)}) for p in r.projects if keep(p.bullets)
            ],
            "achievements": keep(r.achievements),
        }
    )
    draft.ranking = [b for b in draft.ranking if b not in gone]
    return dropped


async def render_one_page(draft: TailoredDraft) -> tuple[RenderedResume, list[str]]:
    """Render; on overflow drop the lowest-ranked non-pinned bullets and re-render (max 3 renders)."""
    dropped: list[str] = []
    for attempt in range(1, MAX_RENDER_ATTEMPTS + 1):
        rendered = await render_resume(draft.resume, draft.section_order)
        pages, extra_lines = await asyncio.to_thread(overflow, rendered.pdf)
        if pages <= 1:
            return rendered, dropped
        if attempt == MAX_RENDER_ATTEMPTS:
            raise PageOverflowError(pages)
        # Each bullet removed also frees spacing; asking for a couple of extra lines avoids a 3rd pass.
        removed = drop_lowest_ranked(draft, extra_lines + 2)
        if not removed:
            raise PageOverflowError(pages)
        dropped += removed
    raise AssertionError("unreachable")


# --- diff ------------------------------------------------------------------------------------------


def _entry_bullets(resume: MasterResume) -> list[list[Bullet]]:
    groups = [e.bullets for e in resume.entries()]
    return [*groups, list(resume.achievements)]


def resume_diff(master: MasterResume, tailored: MasterResume) -> list[ResumeChange]:
    """Per bullet, in master order: removed, rephrased (incl. JD respelling) or reordered within its entry."""
    after = {b.id: b for b in tailored.all_bullets()}
    tailored_positions: dict[str, int] = {}
    for group in _entry_bullets(tailored):
        for i, b in enumerate(group):
            tailored_positions[b.id] = i

    changes: list[ResumeChange] = []
    for group in _entry_bullets(master):
        kept = [b for b in group if b.id in after]
        master_positions = {b.id: i for i, b in enumerate(kept)}
        for bullet in group:
            new = after.get(bullet.id)
            if new is None:
                changes.append(
                    ResumeChange(bullet_id=bullet.id, change="removed", before=bullet.text, after=None)
                )
            elif new.text != bullet.text:
                changes.append(
                    ResumeChange(bullet_id=bullet.id, change="rephrased", before=bullet.text, after=new.text)
                )
            elif master_positions[bullet.id] != tailored_positions[bullet.id]:
                changes.append(
                    ResumeChange(bullet_id=bullet.id, change="reordered", before=bullet.text, after=new.text)
                )
    return changes
