from collections import defaultdict
from datetime import UTC, datetime

from app.services.email.gmail import GmailClient, OutgoingEmail, SentMessage, ThreadMessage


class FakeGmailClient(GmailClient):
    """In-memory mailbox. `sent` records everything sent; `add_message` simulates replies/bounces."""

    def __init__(self, user_email: str) -> None:
        self.user_email = user_email
        self.sent: list[OutgoingEmail] = []
        self._threads: dict[str, list[ThreadMessage]] = defaultdict(list)
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"

    async def send(self, message: OutgoingEmail) -> SentMessage:
        message_id = self._next_id("msg")
        thread_id = message.thread_id or self._next_id("thread")
        self.sent.append(message)
        self._threads[thread_id].append(
            ThreadMessage(
                message_id=message_id,
                from_address=self.user_email,
                to_address=message.to,
                subject=message.subject,
                body=message.body,
                sent_at=datetime.now(UTC),
            )
        )
        return SentMessage(message_id=message_id, thread_id=thread_id)

    async def get_thread(self, thread_id: str) -> list[ThreadMessage]:
        return list(self._threads.get(thread_id, []))

    def add_message(
        self, thread_id: str, from_address: str, body: str, subject: str = "Re:"
    ) -> ThreadMessage:
        message = ThreadMessage(
            message_id=self._next_id("msg"),
            from_address=from_address,
            to_address=self.user_email,
            subject=subject,
            body=body,
            sent_at=datetime.now(UTC),
        )
        self._threads[thread_id].append(message)
        return message
