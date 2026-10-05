"""Deterministic TailorPlan validator (PLAN.md Phase 4, invariant 2).

The tailored resume may contain nothing absent from the master resume. The LLM only proposes; this
module decides. Every rule returns structured issues so the tailor can retry once with them.
"""

import re

from app.schemas.resume import Bullet, MasterResume
from app.schemas.tailor import SectionKey, TailorIssue, TailorPlan
from app.services.resume.skills import SkillLexicon

MAX_GROWTH = 1.3  # rephrased text may be at most 1.3x the original's length

_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*)(\s*(?:%|percent\b|per cent\b))?", re.IGNORECASE)
# "one" is left out: it's mostly a pronoun ("one of the first").
_NUMBER_WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "twelve": "12", "fifteen": "15", "twenty": "20",
    "hundred": "100", "thousand": "1000", "million": "1000000", "half": "50%", "double": "2",
    "twice": "2",
}  # fmt: skip
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)


def numbers_in(text: str) -> set[str]:
    """Numbers and percentages as normalised tokens: "1,200" → "1200", "40 %" → "40%", "two" → "2".
    A percentage also yields its bare number, so "40%" in the original allows "40" (not vice versa)."""
    found: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        number = match.group(1).replace(",", "")
        if match.group(2):
            found.add(number + "%")
        found.add(number)
    for match in _NUMBER_WORD_RE.finditer(text):
        found.add(_NUMBER_WORDS[match.group(1).lower()])
    return found


def new_numbers(rephrased: str, original: str) -> list[str]:
    allowed = numbers_in(original)
    tokens = {
        (m.group(1).replace(",", "") + ("%" if m.group(2) else "")) for m in _NUMBER_RE.finditer(rephrased)
    }
    tokens |= {_NUMBER_WORDS[m.group(1).lower()] for m in _NUMBER_WORD_RE.finditer(rephrased)}
    return sorted(t for t in tokens if t not in allowed)


def master_skill_set(master: MasterResume, lexicon: SkillLexicon) -> set[str]:
    """Canonical names of every skill in the master's skills section, project tech and bullet tags."""
    raw = [s for items in master.skills.values() for s in items]
    raw += [t for p in master.projects for t in p.tech]
    raw += [s for b in master.all_bullets() for s in b.skills]
    return set(lexicon.normalize_all(raw))


def new_skills(rephrased: str, original: str, allowed: set[str], lexicon: SkillLexicon) -> list[str]:
    """Skills mentioned in `rephrased` that are neither allowed nor already in `original`."""
    before = set(lexicon.find_in_text(original))
    found = lexicon.find_in_text(rephrased)
    return sorted(
        next(iter(sorted(spellings)))
        for canonical, spellings in found.items()
        if canonical not in allowed and canonical not in before
    )


def bullet_context(master: MasterResume) -> dict[str, str]:
    """Bullet id → the header of the entry it belongs to (project name and tech, role and company,
    degree and institution). Naming what the entry already names isn't new information."""
    context: dict[str, str] = {}
    for e in master.education:
        context.update({b.id: " ".join(filter(None, [e.degree, e.field, e.institution])) for b in e.bullets})
    for x in master.experience:
        context.update({b.id: f"{x.role} {x.org}" for b in x.bullets})
    for p in master.projects:
        context.update({b.id: f"{p.name} {' '.join(p.tech)}" for b in p.bullets})
    return context


def _sections_of(master: MasterResume) -> dict[SectionKey, list[Bullet]]:
    return {
        "education": [b for e in master.education for b in e.bullets],
        "experience": [b for e in master.experience for b in e.bullets],
        "projects": [b for p in master.projects for b in p.bullets],
        "achievements": list(master.achievements),
    }


def validate_plan(plan: TailorPlan, master: MasterResume, lexicon: SkillLexicon) -> list[TailorIssue]:
    issues: list[TailorIssue] = []
    bullets = {b.id: b for b in master.all_bullets()}
    master_skills = master_skill_set(master, lexicon)
    context = bullet_context(master)

    # 1. Selected bullets exist; pinned bullets of included sections are present.
    for bullet_id in plan.selected_bullet_ids:
        if bullet_id not in bullets:
            issues.append(
                TailorIssue(
                    code="unknown_bullet",
                    bullet_id=bullet_id,
                    message=f"{bullet_id!r} is not a bullet id in the master resume",
                )
            )
    selected = set(plan.selected_bullet_ids)
    if not selected & bullets.keys():
        issues.append(TailorIssue(code="no_bullets", message="select at least one bullet"))
    for section, section_bullets in _sections_of(master).items():
        if section not in plan.section_order:
            continue
        for bullet in section_bullets:
            if bullet.pinned and bullet.id not in selected:
                issues.append(
                    TailorIssue(
                        code="pinned_missing",
                        bullet_id=bullet.id,
                        message=f"{bullet.id!r} is pinned and its section ({section}) is included",
                    )
                )

    # 2-4. Rephrasings: no new skills (beyond the bullet's tags, the master's skills and its own
    #      entry's header) or numbers, at most 1.3x as long.
    for bullet_id, text in plan.rephrasing_map().items():
        original = bullets.get(bullet_id)
        if original is None:
            if bullet_id not in selected:  # reported above when selected
                issues.append(
                    TailorIssue(
                        code="unknown_bullet",
                        bullet_id=bullet_id,
                        message=f"rephrasing for unknown bullet id {bullet_id!r}",
                    )
                )
            continue
        allowed = set(lexicon.normalize_all(original.skills)) | master_skills
        if added := new_skills(text, f"{original.text} {context.get(bullet_id, '')}", allowed, lexicon):
            issues.append(
                TailorIssue(
                    code="new_skill",
                    bullet_id=bullet_id,
                    message=f"mentions {', '.join(added)}, which the master resume doesn't list",
                )
            )
        if added_numbers := new_numbers(text, original.text):
            issues.append(
                TailorIssue(
                    code="new_number",
                    bullet_id=bullet_id,
                    message=f"uses {', '.join(added_numbers)}, which the original bullet doesn't say",
                )
            )
        if len(text.strip()) > MAX_GROWTH * len(original.text.strip()):
            issues.append(
                TailorIssue(
                    code="too_long",
                    bullet_id=bullet_id,
                    message=f"rephrasing is {len(text.strip())} chars; at most "
                    f"{int(MAX_GROWTH * len(original.text.strip()))} (1.3x the original)",
                )
            )

    # 5. skills_to_show ⊆ master skills.
    unknown = [s for s in plan.skills_to_show if lexicon.normalize(s) not in master_skills]
    if unknown:
        issues.append(
            TailorIssue(
                code="unknown_skill_shown",
                message=f"skills_to_show has {', '.join(unknown)}, which the master resume doesn't list",
            )
        )

    # The summary is a rephrasing of the master summary, held to the same rules; none if there is none.
    if plan.summary:
        if not master.summary:
            issues.append(
                TailorIssue(code="summary_not_allowed", message="the master resume has no summary to adapt")
            )
        else:
            if added := new_skills(plan.summary, master.summary, master_skills, lexicon):
                issues.append(TailorIssue(code="new_skill", message=f"summary mentions {', '.join(added)}"))
            if added_numbers := new_numbers(plan.summary, master.summary):
                issues.append(
                    TailorIssue(code="new_number", message=f"summary uses {', '.join(added_numbers)}")
                )
            if len(plan.summary.strip()) > MAX_GROWTH * len(master.summary.strip()):
                issues.append(TailorIssue(code="too_long", message="summary is over 1.3x the original"))
    return issues
