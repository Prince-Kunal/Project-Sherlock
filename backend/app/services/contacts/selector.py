"""Who to email at a company (PLAN.md Phase 5). Rule-based, no LLM.

- Startups (size_hint == startup or ≤ 50 people): founder/CTO → engineering manager → recruiter.
- Everyone else: engineering manager or team lead in a relevant department → recruiter → senior engineer.
- Never: suppressed addresses, invalid addresses, or anyone contacted by any user in the last 30 days.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models import Company, Contact
from app.models.enums import RoleCategory, SizeHint, VerificationStatus

COOLDOWN_DAYS = 30
STARTUP_MAX_EMPLOYEES = 50

_FOUNDER_RE = re.compile(r"\b(co-?founder|founder|ceo|cto|chief|owner)\b", re.I)
_RECRUITER_RE = re.compile(r"\b(recruit\w*|talent|hiring|human resources|hr|people|campus)\b", re.I)
_LEAD_RE = re.compile(r"\b(manager|head|director|vp|vice president|lead)\b", re.I)
_ENG_RE = re.compile(
    r"\b(engineer\w*|software|technology|tech|platform|backend|frontend|developer|development|data|"
    r"infrastructure|sre|devops|mobile|product engineering|machine learning|ml|ai)\b",
    re.I,
)
_ENGINEER_RE = re.compile(r"\b(engineer|developer|sde|programmer|architect|scientist)\b", re.I)
_SENIOR_RE = re.compile(r"\b(senior|sr|staff|principal|lead)\b", re.I)
# Hunter departments where an engineering manager would sit.
_RELEVANT_DEPARTMENTS = {"it", "engineering", "management", "executive"}


def categorize(
    title: str | None, seniority: str | None = None, department: str | None = None
) -> RoleCategory:
    """Role category from a job title (provider seniority/department as tie-breakers)."""
    title = title or ""
    if _FOUNDER_RE.search(title):
        return RoleCategory.FOUNDER
    if _RECRUITER_RE.search(title) or (department or "").lower() == "hr":
        return RoleCategory.RECRUITER
    if _LEAD_RE.search(title) and (
        _ENG_RE.search(title) or (department or "").lower() in {"it", "engineering"}
    ):
        return RoleCategory.ENG_MANAGER
    if _ENGINEER_RE.search(title):
        return RoleCategory.ENGINEER
    return RoleCategory.OTHER


def is_startup(company: Company) -> bool:
    if company.employee_count is not None:
        return company.employee_count <= STARTUP_MAX_EMPLOYEES
    return company.size_hint == SizeHint.STARTUP


@dataclass(frozen=True)
class Eligibility:
    suppressed: frozenset[str]
    now: datetime

    def allows(self, contact: Contact) -> bool:
        if contact.email.lower() in self.suppressed:
            return False
        if contact.verification_status == VerificationStatus.INVALID:
            return False
        last = contact.last_contacted_at
        return not (last and self.now - last < timedelta(days=COOLDOWN_DAYS))


def _tier(contact: Contact, startup: bool) -> int | None:
    role = contact.role_category
    title = contact.title or ""
    if startup:
        if role == RoleCategory.FOUNDER:
            return 0 if re.search(r"\bcto\b|chief technology", title, re.I) else 1
        return {RoleCategory.ENG_MANAGER: 2, RoleCategory.RECRUITER: 3}.get(role)
    if role == RoleCategory.ENG_MANAGER:
        department = (contact.department or "").lower()
        return 0 if not department or department in _RELEVANT_DEPARTMENTS else None
    if role == RoleCategory.RECRUITER:
        return 1
    if role == RoleCategory.ENGINEER and (
        _SENIOR_RE.search(title) or (contact.seniority or "").lower() in {"senior", "executive"}
    ):
        return 2
    return None


_VERIFICATION_ORDER = {
    VerificationStatus.VALID: 0,
    VerificationStatus.ACCEPT_ALL: 1,
    VerificationStatus.UNKNOWN: 2,
}


def rank_contacts(contacts: list[Contact], *, startup: bool, eligibility: Eligibility) -> list[Contact]:
    """Eligible contacts in the order to try them; people outside the rules' roles are left out."""
    ranked = []
    for contact in contacts:
        tier = _tier(contact, startup)
        if tier is None or not eligibility.allows(contact):
            continue
        ranked.append(
            (
                tier,
                _VERIFICATION_ORDER.get(contact.verification_status, 3),
                -(contact.confidence or 0),
                contact.full_name,
                contact,
            )
        )
    ranked.sort(key=lambda item: item[:4])
    return [item[4] for item in ranked]
