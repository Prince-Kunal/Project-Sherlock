"""MasterResume and its LLM parsing contract (PLAN.md §6).

Dates are stored as "YYYY-MM", "YYYY", or "present" and formatted only at render time, so every
rendered resume uses one consistent date style (§6.1).
"""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

_DATE_RE = re.compile(r"^(\d{4}(-(0[1-9]|1[0-2]))?|present)$")
_PRESENT = {"present", "current", "now", "ongoing", "today", "till date", "till now", "to date"}
_MONTHS = {
    name: n
    for n, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
_MONTH_YEAR_RE = re.compile(r"^(\d{1,2})-(\d{4})$")
_NAMED_RE = re.compile(r"^([a-z]+)-(\d{4})$")


def _check_date(value: str | None) -> str | None:
    """Accept the usual ways people write a resume date ("2026-9", "09/2026", "Sep 2026", "Present")
    and store one form: "YYYY-MM", "YYYY" or "present"."""
    if value is None:
        return None
    raw = " ".join(value.strip().lower().split())
    if not raw:
        return None
    if raw in _PRESENT:
        return "present"
    # Any separator (slash, dot, space, comma, the dashes macOS substitutes) becomes "-".
    text = re.sub("[\\s/.,\u2010-\u2015\u2212-]+", "-", raw).strip("-")
    year = month = None
    if match := _YEAR_MONTH_RE.match(text):
        year, month = match[1], int(match[2])
    elif match := _MONTH_YEAR_RE.match(text):
        month, year = int(match[1]), match[2]
    elif (match := _NAMED_RE.match(text)) and match[1] in _MONTHS:
        month, year = _MONTHS[match[1]], match[2]
    if year is not None and month is not None and 1 <= month <= 12:
        text = f"{year}-{month:02d}"
    if not _DATE_RE.match(text):
        raise ValueError(f'"{value.strip()}" isn\'t a date; write it like 2026-09, 2026 or present')
    return text


ResumeDate = Annotated[str | None, AfterValidator(_check_date)]
NonEmpty = Annotated[str, Field(min_length=1)]


class Link(BaseModel):
    label: str  # e.g. "LinkedIn", "GitHub", "Portfolio"
    url: str


class Basics(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[Link] = Field(default_factory=list)


class Bullet(BaseModel):
    id: str  # stable, e.g. "exp1-b2"
    text: NonEmpty
    skills: list[str] = Field(default_factory=list)  # canonical lowercase names (see skills.py)
    pinned: bool = False  # always include when the parent section is included


class Education(BaseModel):
    id: str
    institution: NonEmpty
    degree: str | None = None
    field: str | None = None
    location: str | None = None
    start: ResumeDate = None
    end: ResumeDate = None
    gpa: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class Experience(BaseModel):
    id: str
    org: NonEmpty
    role: NonEmpty
    location: str | None = None
    start: ResumeDate = None
    end: ResumeDate = None
    bullets: list[Bullet] = Field(default_factory=list)


class Project(BaseModel):
    id: str
    name: NonEmpty
    link: str | None = None
    tech: list[str] = Field(default_factory=list)
    start: ResumeDate = None  # extension of PLAN §6: resumes usually date their projects
    end: ResumeDate = None
    bullets: list[Bullet] = Field(default_factory=list)


class MasterResume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basics: Basics
    summary: str | None = None
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)  # {"languages": ["Python", ...], ...}
    achievements: list[Bullet] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_unique(self) -> "MasterResume":
        seen: set[str] = set()
        # Empty ids are allowed on input: they mark new items, and get assigned on save.
        for item_id in filter(None, (i.strip() for i in self.all_ids())):
            if item_id in seen:
                raise ValueError(f"duplicate id {item_id!r}")
            seen.add(item_id)
        return self

    def entries(self) -> list["Education | Experience | Project"]:
        return [*self.education, *self.experience, *self.projects]

    def all_ids(self) -> list[str]:
        ids: list[str] = []
        for entry in self.entries():
            ids.append(entry.id)
            ids.extend(b.id for b in entry.bullets)
        ids.extend(b.id for b in self.achievements)
        return ids

    def all_bullets(self) -> list[Bullet]:
        bullets = [b for e in self.entries() for b in e.bullets]
        return bullets + list(self.achievements)


# --- LLM contract for parse_resume.md: no ids (assigned in code), no email/phone (never sent to the LLM).


class ParsedBullet(BaseModel):
    text: NonEmpty
    skills: list[str] = Field(default_factory=list)


class ParsedBasics(BaseModel):
    name: str
    location: str | None = None
    links: list[Link] = Field(default_factory=list)


class ParsedEducation(BaseModel):
    institution: NonEmpty
    degree: str | None = None
    field: str | None = None
    location: str | None = None
    start: ResumeDate = None
    end: ResumeDate = None
    gpa: str | None = None
    bullets: list[ParsedBullet] = Field(default_factory=list)


class ParsedExperience(BaseModel):
    org: NonEmpty
    role: NonEmpty
    location: str | None = None
    start: ResumeDate = None
    end: ResumeDate = None
    bullets: list[ParsedBullet] = Field(default_factory=list)


class ParsedProject(BaseModel):
    name: NonEmpty
    link: str | None = None
    tech: list[str] = Field(default_factory=list)
    start: ResumeDate = None
    end: ResumeDate = None
    bullets: list[ParsedBullet] = Field(default_factory=list)


class SkillGroup(BaseModel):
    category: str  # e.g. "Languages"
    items: list[str]


class ParsedResume(BaseModel):
    basics: ParsedBasics
    summary: str | None = None
    education: list[ParsedEducation] = Field(default_factory=list)
    experience: list[ParsedExperience] = Field(default_factory=list)
    projects: list[ParsedProject] = Field(default_factory=list)
    # A list rather than a dict: open-ended object keys are poorly supported by structured output.
    skills: list[SkillGroup] = Field(default_factory=list)
    achievements: list[ParsedBullet] = Field(default_factory=list)


class TaggedBullet(BaseModel):
    """tag_skills.md output item."""

    index: int
    skills: list[str]


# --- API


class ResumeVersionOut(BaseModel):
    version: int
    is_current: bool
    created_at: str


class ResumeOut(BaseModel):
    version: int
    data: MasterResume
