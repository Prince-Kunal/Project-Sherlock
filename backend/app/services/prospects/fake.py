"""In-memory CompanySearchProvider for tests and USE_FAKES=true: the recorded YC directory slice
(tests/fixtures/sources/yc/companies.json) or companies given directly."""

import json
from pathlib import Path

from app.services.prospects.base import CompanyIn, CompanySearchProvider
from app.services.prospects.filters import fits_target
from app.services.prospects.yc import PAGE_SIZE, parse_company

YC_FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sources" / "yc" / "companies.json"


def load_yc_fixture(path: Path = YC_FIXTURE) -> list[CompanyIn]:
    if not path.exists():
        return []
    parsed = (parse_company(item) for item in json.loads(path.read_text()))
    return [c for c in parsed if c is not None]


class FakeCompanySearch(CompanySearchProvider):
    name = "fake"

    def __init__(self, companies: list[CompanyIn] | None = None) -> None:
        self.companies = load_yc_fixture() if companies is None else list(companies)
        self.calls: list[tuple[list[str], list[str], list[str], int]] = []

    async def search_companies(
        self, industries: list[str], locations: list[str], sizes: list[str], page: int = 1
    ) -> list[CompanyIn]:
        self.calls.append((industries, locations, sizes, page))
        matching = [
            c
            for c in self.companies
            if fits_target(
                tags=c.industry_tags,
                industry=c.industry,
                locations=c.locations,
                size=c.size_hint,
                industries=industries,
                wanted_locations=locations,
                sizes=sizes,
            )
        ]
        start = (max(page, 1) - 1) * PAGE_SIZE
        return matching[start : start + PAGE_SIZE]
