import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    is_admin: bool
    timezone: str
    onboarded_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def onboarded(self) -> bool:
        return self.onboarded_at is not None


class SessionOut(BaseModel):
    token: str
    user: UserOut
