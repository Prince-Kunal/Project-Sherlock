"""The company career-board adapters, by ATS type. All use the ATS's own public, keyless API."""

from app.models.enums import AtsType
from app.services.sources.ashby import AshbySource
from app.services.sources.base import JobSource
from app.services.sources.greenhouse import GreenhouseSource
from app.services.sources.http import PoliteHttpClient
from app.services.sources.lever import LeverSource
from app.services.sources.recruitee import RecruiteeSource
from app.services.sources.smartrecruiters import SmartRecruitersSource
from app.services.sources.workable import WorkableSource


def board_sources(http: PoliteHttpClient) -> dict[AtsType, JobSource]:
    return {
        AtsType.GREENHOUSE: GreenhouseSource(http),
        AtsType.LEVER: LeverSource(http),
        AtsType.ASHBY: AshbySource(http),
        AtsType.SMARTRECRUITERS: SmartRecruitersSource(http),
        AtsType.WORKABLE: WorkableSource(http),
        AtsType.RECRUITEE: RecruiteeSource(http),
    }
