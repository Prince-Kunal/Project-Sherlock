"""Importing this package registers every model on Base.metadata (needed by Alembic)."""

from app.models.base import Base
from app.models.company import Company, CompanyMatch, ProspectTarget, UserCompanyBlock
from app.models.contact import Contact, SuppressionEntry
from app.models.job import Job, JobMatch
from app.models.outreach import Outreach, OutreachEvent
from app.models.resume import MasterResume
from app.models.usage import UsageLedger
from app.models.user import AllowedEmail, OAuthToken, User, UserLLMKey, UserPreferences

__all__ = [
    "AllowedEmail",
    "Base",
    "Company",
    "CompanyMatch",
    "Contact",
    "Job",
    "JobMatch",
    "MasterResume",
    "OAuthToken",
    "Outreach",
    "OutreachEvent",
    "ProspectTarget",
    "SuppressionEntry",
    "UsageLedger",
    "User",
    "UserCompanyBlock",
    "UserLLMKey",
    "UserPreferences",
]
