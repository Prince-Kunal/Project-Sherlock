"""A/B draft styles (PLAN.md Phase 10). Every first email is written in one of two shapes; the shape is
stored on the outreach (`draft_variant`) so replies can be compared per style (outreach analytics).

New drafts get the style this user has used less so far (ties go to A), so the two stay balanced
however many drafts there are. A user can also lock to one style (`user_preferences.draft_style`)
once they've seen which gets more replies. Regenerating a draft keeps its style; follow-ups have
their own prompt and aren't part of the test.
"""

import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outreach

Variant = Literal["a", "b"]
VARIANTS: tuple[Variant, Variant] = ("a", "b")

STYLE_NAMES: dict[str, str] = {"a": "Ask first", "b": "Work first"}

# Inserted into draft_email / draft_open_email under "Shape of this email".
STYLES: dict[str, str] = {
    "a": (
        "Ask first. The first sentence is the ask itself. Then one or two sentences on what the "
        "candidate has built that matters here. End with the easy way out and the attached resume. "
        "One paragraph, or two if it reads better."
    ),
    "b": (
        "Work first. Open with one sentence about the single thing the candidate built that is "
        "closest to this team's work, told plainly. The ask comes right after it, in the second or "
        "third sentence. End with the easy way out and the attached resume. Two short paragraphs."
    ),
}


async def choose_variant(session: AsyncSession, user_id: uuid.UUID, locked: str = "ab") -> Variant:
    """The style for this user's next new draft: `locked` ("a" or "b") if they chose one, otherwise
    whichever they've had fewer of."""
    if locked in VARIANTS:
        return "a" if locked == "a" else "b"
    rows = await session.execute(
        select(Outreach.draft_variant, func.count())
        .where(Outreach.user_id == user_id, Outreach.draft_variant.is_not(None))
        .group_by(Outreach.draft_variant)
    )
    counts = {variant: count for variant, count in rows}
    return "b" if counts.get("b", 0) < counts.get("a", 0) else "a"
