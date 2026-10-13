"""Outcome analytics (PLAN.md Phase 10): reply rate by contact role, company stage, draft style and
mode, over the user's first emails sent in a window. A reply means any human answer (opt-outs
included: someone read it). Referrals and interviews come from the outcome the user records.

The A/B verdict needs `MIN_PER_VARIANT` emails per style and a gap of `MIN_GAP_POINTS` before it
names a leader; small samples swing wildly, so below that it says it's too early.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Outreach
from app.models.enums import CampaignType, Outcome, RoleCategory, SizeHint
from app.services.email.variants import STYLE_NAMES

MIN_PER_VARIANT = 8
MIN_GAP_POINTS = 10

ROLE_LABELS = {
    RoleCategory.FOUNDER: "Founders",
    RoleCategory.ENG_MANAGER: "Engineering managers",
    RoleCategory.ENGINEER: "Engineers",
    RoleCategory.RECRUITER: "Recruiters",
    RoleCategory.OTHER: "Others",
}
STAGE_LABELS = {
    SizeHint.STARTUP: "Startups",
    SizeHint.MID: "Mid-size",
    SizeHint.LARGE: "Large companies",
    SizeHint.UNKNOWN: "Size unknown",
}
MODE_LABELS = {CampaignType.JOB: "Job-linked", CampaignType.OPEN: "Open outreach"}


@dataclass
class Bucket:
    key: str
    label: str
    sent: int = 0
    replied: int = 0
    referred: int = 0
    interview: int = 0

    @property
    def reply_rate(self) -> float | None:
        return round(100 * self.replied / self.sent, 1) if self.sent else None


@dataclass
class Analytics:
    since: datetime | None
    sent: int = 0
    replied: int = 0
    referred: int = 0
    interview: int = 0
    by_role: list[Bucket] = field(default_factory=list)
    by_stage: list[Bucket] = field(default_factory=list)
    by_variant: list[Bucket] = field(default_factory=list)
    by_mode: list[Bucket] = field(default_factory=list)
    leader: str | None = None  # the draft style with more replies, once the data says so
    verdict: str = ""

    @property
    def reply_rate(self) -> float | None:
        return round(100 * self.replied / self.sent, 1) if self.sent else None


def _buckets(rows: list[tuple[str, str]], counts: dict[str, Bucket]) -> list[Bucket]:
    order = [key for key, _ in rows]
    return sorted((b for b in counts.values() if b.sent), key=lambda b: (-b.sent, order.index(b.key)))


def style_verdict(by_variant: list[Bucket]) -> tuple[str | None, str]:
    styles = {b.key: b for b in by_variant if b.key in STYLE_NAMES}
    a, b = styles.get("a"), styles.get("b")
    if a is None or b is None or min(a.sent, b.sent) < MIN_PER_VARIANT:
        have = min(a.sent if a else 0, b.sent if b else 0)
        return None, (
            f"Too early to compare the two email styles: each needs {MIN_PER_VARIANT} sent emails "
            f"(the smaller has {have})."
        )
    gap = (a.reply_rate or 0) - (b.reply_rate or 0)
    if abs(gap) < MIN_GAP_POINTS:
        return None, (
            f"Both styles get about the same reply rate so far ({STYLE_NAMES['a']} {a.reply_rate}%, "
            f"{STYLE_NAMES['b']} {b.reply_rate}%)."
        )
    win, lose = (a, b) if gap > 0 else (b, a)
    return win.key, (
        f"{STYLE_NAMES[win.key]} gets more replies: {win.reply_rate}% ({win.replied} of {win.sent}) "
        f"against {lose.reply_rate}% ({lose.replied} of {lose.sent}) for {STYLE_NAMES[lose.key]}."
    )


async def outreach_analytics(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, days: int | None = 90
) -> Analytics:
    since = now - timedelta(days=days) if days else None
    query = (
        select(Outreach, Contact.role_category, Company.size_hint)
        .join(Company, Company.id == Outreach.company_id)
        .outerjoin(Contact, Contact.id == Outreach.contact_id)
        .where(Outreach.user_id == user_id, Outreach.sent_at.is_not(None))
    )
    if since is not None:
        query = query.where(Outreach.sent_at >= since)
    result = Analytics(since=since)
    roles: dict[str, Bucket] = {}
    stages: dict[str, Bucket] = {}
    variants: dict[str, Bucket] = {}
    modes: dict[str, Bucket] = {}
    role_rows = [(r.value, label) for r, label in ROLE_LABELS.items()]
    stage_rows = [(s.value, label) for s, label in STAGE_LABELS.items()]
    variant_rows = [*STYLE_NAMES.items(), ("none", "Before the style test")]
    mode_rows = [(m.value, label) for m, label in MODE_LABELS.items()]
    labels = {
        "role": dict(role_rows),
        "stage": dict(stage_rows),
        "variant": dict(variant_rows),
        "mode": dict(mode_rows),
    }

    for outreach, role, size in (await session.execute(query)).all():
        keys = {
            "role": (role or RoleCategory.OTHER).value,
            "stage": (size or SizeHint.UNKNOWN).value,
            "variant": outreach.draft_variant or "none",
            "mode": outreach.campaign_type.value,
        }
        replied = outreach.replied_at is not None
        result.sent += 1
        result.replied += replied
        result.referred += outreach.outcome == Outcome.REFERRED
        result.interview += outreach.outcome == Outcome.INTERVIEW
        for dimension, buckets in (
            ("role", roles),
            ("stage", stages),
            ("variant", variants),
            ("mode", modes),
        ):
            key = keys[dimension]
            bucket = buckets.setdefault(key, Bucket(key, labels[dimension].get(key, key)))
            bucket.sent += 1
            bucket.replied += replied
            bucket.referred += outreach.outcome == Outcome.REFERRED
            bucket.interview += outreach.outcome == Outcome.INTERVIEW

    result.by_role = _buckets(role_rows, roles)
    result.by_stage = _buckets(stage_rows, stages)
    result.by_variant = _buckets(variant_rows, variants)
    result.by_mode = _buckets(mode_rows, modes)
    result.leader, result.verdict = style_verdict(result.by_variant)
    return result
