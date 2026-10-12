"""Company search for open outreach (PLAN.md Phase 8): companies matching a prospect target's
industries, locations and sizes, whether or not they have an opening posted.

The plan named Apollo's organization search; on a free Apollo account it isn't available (paid plans
only, 1 credit per page), so the implementation is the public YC company directory (yc.py). Companies
already in the database (seed list, job feed, ones a user added) are candidates too, without any
provider.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from app.models.enums import SizeHint


class CompanyIn(BaseModel):
    name: str
    domain: str | None
    description: str | None = None  # a few sentences in the company's own words
    industry: str | None = None
    industry_tags: list[str] = Field(default_factory=list)  # lowercase
    locations: list[str] = Field(default_factory=list)  # offices, then regions ("India", "Remote")
    hq_location: str | None = None
    employee_count: int | None = None
    size_hint: SizeHint = SizeHint.UNKNOWN


class CompanySearchError(Exception):
    """The directory couldn't be fetched or read."""


class CompanySearchProvider(ABC):
    name: str

    @abstractmethod
    async def search_companies(
        self, industries: list[str], locations: list[str], sizes: list[str], page: int = 1
    ) -> list[CompanyIn]:
        """One page of active companies matching every non-empty filter (an empty list matches all).
        An empty page means there are no more results."""
