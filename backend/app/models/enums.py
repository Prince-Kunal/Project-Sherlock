"""Enumerated string values used across models. Stored as VARCHAR + CHECK constraint (not native PG enums)
so adding a value is a plain constraint swap in a migration."""

from enum import StrEnum


class EmploymentType(StrEnum):
    INTERNSHIP = "internship"
    FULL_TIME = "full_time"


class CompanyStage(StrEnum):
    STARTUP = "startup"
    MID = "mid"
    LARGE = "large"


class AtsType(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    NONE = "none"


class SizeHint(StrEnum):
    STARTUP = "startup"
    MID = "mid"
    LARGE = "large"
    UNKNOWN = "unknown"


class CompanyMatchStatus(StrEnum):
    NEW = "new"
    QUEUED = "queued"
    CONTACTED = "contacted"
    HIDDEN = "hidden"


class JobSourceType(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    ADZUNA = "adzuna"
    HN = "hn"
    MANUAL = "manual"


class JobMatchStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    HIDDEN = "hidden"
    IN_PIPELINE = "in_pipeline"
    EXPIRED = "expired"


class EmailSource(StrEnum):
    HUNTER = "hunter"
    APOLLO = "apollo"
    MANUAL = "manual"
    PATTERN = "pattern"
    HN = "hn"  # an address the company posted in its HN "Who is hiring" comment


class VerificationStatus(StrEnum):
    VALID = "valid"
    ACCEPT_ALL = "accept_all"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class RoleCategory(StrEnum):
    FOUNDER = "founder"
    ENG_MANAGER = "eng_manager"
    ENGINEER = "engineer"
    RECRUITER = "recruiter"
    OTHER = "other"


class CampaignType(StrEnum):
    JOB = "job"
    OPEN = "open"


class OutreachStatus(StrEnum):
    """States from PLAN.md §7. Only services/email/state.py may change an outreach's status."""

    DRAFTING = "drafting"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    SENT = "sent"
    REPLIED = "replied"
    FOLLOWUP_DUE = "followup_due"
    SEND_FAILED = "send_failed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CLOSED = "closed"


# Outreach rows in these states don't count toward "one active outreach per (user, company)".
INACTIVE_OUTREACH_STATUSES = (OutreachStatus.CLOSED, OutreachStatus.SKIPPED, OutreachStatus.FAILED)


class Outcome(StrEnum):
    NONE = "none"
    REFERRED = "referred"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    NOT_HIRING = "not_hiring"


class OutreachEventType(StrEnum):
    DRAFTED = "drafted"
    EDITED = "edited"
    REGENERATED = "regenerated"
    APPROVED = "approved"
    SKIPPED = "skipped"
    SCHEDULED = "scheduled"
    SENT = "sent"
    SEND_FAILED = "send_failed"
    REPLY_DETECTED = "reply_detected"
    FOLLOWUP_DRAFTED = "followup_drafted"
    FOLLOWUP_SENT = "followup_sent"
    BOUNCED = "bounced"
    CLOSED = "closed"
    OUTCOME_SET = "outcome_set"
    UPGRADED_TO_JOB = "upgraded_to_job"  # Phase 8 upgrade path
    FAILED = "failed"  # payload: {"reason": ...}
    RETRIED = "retried"  # failed → drafting after the cause was fixed (e.g. a contact added by hand)
    CONTACT_CHANGED = "contact_changed"


class SuppressionReason(StrEnum):
    OPT_OUT = "opt_out"
    BOUNCE = "bounce"
    MANUAL = "manual"


class OAuthProvider(StrEnum):
    GOOGLE = "google"


class LLMProvider(StrEnum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


class ServiceKeyType(StrEnum):
    """Non-LLM services each user brings their own key for (Hunter's free tier is per account)."""

    HUNTER = "hunter"
    APOLLO = "apollo"


class UsageProvider(StrEnum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    HUNTER = "hunter"
    APOLLO = "apollo"
    ADZUNA = "adzuna"
