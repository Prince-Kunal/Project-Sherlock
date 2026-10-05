"""Deterministic LLMClient for tests and USE_FAKES=true. Never calls a network.

Responses are recorded JSON strings keyed by prompt name. Queue several for one prompt to script
retries (e.g. an invalid response followed by a valid one); the last response repeats once the queue
is down to one.
"""

import json
from collections import defaultdict
from typing import Any

from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMAuthError, LLMClient, LLMRequest


class FakeLLMClient(LLMClient):
    def __init__(
        self,
        responses: dict[str, list[str] | str] | None = None,
        cache: LLMCache | None = None,
        rejected_keys: set[str] | None = None,
    ) -> None:
        super().__init__(cache)
        self._responses: dict[str, list[str]] = defaultdict(list)
        self.calls: list[tuple[LLMRequest, str]] = []
        self.rejected_keys = rejected_keys or set()
        self.add_response("verify_key", {"ok": True})
        for name, value in (responses or {}).items():
            self._responses.pop(name, None)
            self.add_response(name, value)

    def add_response(self, prompt_name: str, response: list[str] | str | Any) -> None:
        """Queue responses. Non-string values are JSON-encoded."""
        items = response if isinstance(response, list) else [response]
        for item in items:
            self._responses[prompt_name].append(item if isinstance(item, str) else json.dumps(item))

    async def _complete_json(self, request: LLMRequest, prompt: str, schema: dict[str, Any]) -> str:
        self.calls.append((request, prompt))
        if request.api_key in self.rejected_keys:
            raise LLMAuthError("fake: key rejected")
        queue = self._responses.get(request.prompt_name)
        if not queue:
            raise LookupError(f"FakeLLMClient has no recorded response for prompt {request.prompt_name!r}")
        return queue.pop(0) if len(queue) > 1 else queue[0]
