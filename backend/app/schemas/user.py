import uuid

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    is_admin: bool
    timezone: str


class SessionOut(BaseModel):
    token: str
    user: UserOut
