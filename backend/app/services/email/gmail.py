"""Gmail interface. The real implementation (users.messages.send / threads.get) arrives in Phase 7."""

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel


class Attachment(BaseModel):
    filename: str
    content_type: str = "application/pdf"
    data: bytes


class OutgoingEmail(BaseModel):
    to: str
    subject: str
    body: str  # plain text
    attachment: Attachment | None = None
    # Follow-ups reply in-thread with no attachment.
    thread_id: str | None = None
    in_reply_to: str | None = None


class SentMessage(BaseModel):
    message_id: str
    thread_id: str


class ThreadMessage(BaseModel):
    message_id: str
    from_address: str
    to_address: str
    subject: str
    body: str
    sent_at: datetime


class GmailClient(ABC):
    """Bound to one user's mailbox."""

    @abstractmethod
    async def send(self, message: OutgoingEmail) -> SentMessage: ...

    @abstractmethod
    async def get_thread(self, thread_id: str) -> list[ThreadMessage]: ...
