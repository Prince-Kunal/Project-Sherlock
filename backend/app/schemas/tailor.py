"""Resume tailoring (PLAN.md Phase 4): the LLM's TailorPlan contract and the results built from it."""

from typing import Literal

from pydantic import BaseModel, Field

from app.services.resume.ats_check import AtsReport, KeywordCoverage

SectionKey = Literal["education", "experience", "projects", "skills", "achievements"]


class Rephrasing(BaseModel):
    bullet_id: str
    text: str = Field(min_length=1)


class TailorPlan(BaseModel):
    """PLAN.md §6 TailorPlan. `rephrasings` is a list rather than a dict (JSON schemas with free-form
    keys are poorly supported by structured output); `jd_keywords` feeds the ATS keyword rule."""

    section_order: list[SectionKey]
    selected_bullet_ids: list[str]  # ordered by relevance within each entry
    rephrasings: list[Rephrasing] = Field(default_factory=list)
    skills_to_show: list[str] = Field(default_factory=list)  # ordered by relevance
    summary: str | None = None
    jd_keywords: list[str] = Field(default_factory=list, max_length=25)  # must-haves, JD spelling

    def rephrasing_map(self) -> dict[str, str]:
        return {r.bullet_id: r.text for r in self.rephrasings}


IssueCode = Literal[
    "unknown_bullet",
    "no_bullets",
    "pinned_missing",
    "new_skill",
    "new_number",
    "too_long",
    "unknown_skill_shown",
    "summary_not_allowed",
]


class TailorIssue(BaseModel):
    code: IssueCode
    message: str
    bullet_id: str | None = None


ChangeKind = Literal["added", "removed", "reordered", "rephrased"]


class ResumeChange(BaseModel):
    bullet_id: str
    change: ChangeKind
    before: str | None
    after: str | None


class TailorPreviewOut(BaseModel):
    match_id: str
    pdf_url: str
    filename: str
    section_order: list[SectionKey]
    diff: list[ResumeChange]
    keyword_coverage: KeywordCoverage
    ats: AtsReport
    bullets_dropped_to_fit: int
