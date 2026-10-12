from collections import defaultdict
from datetime import UTC, datetime

from app.services.email.gmail import GmailClient, OutgoingEmail, SentMessage, ThreadMessage


class FakeGmailClient(GmailClient):
    """In-memory mailbox. `sent` records everything sent; `add_message` simulates replies/bounces;
    `fail_next` makes the next send raise."""

    def __init__(self, user_email: str) -> None:
        self.user_email = user_email
        self.sent: list[OutgoingEmail] = []
        self.fail_next: Exception | None = None
        self._threads: dict[str, list[ThreadMessage]] = defaultdict(list)
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"

    async def send(self, message: OutgoingEmail) -> SentMessage:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
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
                rfc_message_id=f"<{message_id}@fake.mail>",
                snippet=message.body[:100],
            )
        )
        return SentMessage(message_id=message_id, thread_id=thread_id)

    async def get_thread(self, thread_id: str) -> list[ThreadMessage]:
        return list(self._threads.get(thread_id, []))

    def add_message(
        self,
        thread_id: str,
        from_address: str,
        body: str,
        subject: str = "Re:",
        auto_submitted: bool = False,
        sent_at: datetime | None = None,
    ) -> ThreadMessage:
        message_id = self._next_id("msg")
        message = ThreadMessage(
            message_id=message_id,
            from_address=from_address.lower(),
            to_address=self.user_email,
            subject=subject,
            body=body,
            sent_at=sent_at or datetime.now(UTC),
            rfc_message_id=f"<{message_id}@fake.mail>",
            snippet=body[:100],
            auto_submitted=auto_submitted,
        )
        self._threads[thread_id].append(message)
        return message
