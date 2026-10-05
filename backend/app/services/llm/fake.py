"""Deterministic LLMClient for tests and USE_FAKES=true. Never calls a network.

Responses are recorded JSON strings keyed by prompt name. Queue several for one prompt to script
retries (e.g. an invalid response followed by a valid one); the last response repeats once the queue
is down to one.
"""

import json
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMAuthError, LLMClient, LLMRequest


class FakeLLMClient(LLMClient):
    def __init__(
        self,
        responses: dict[str, Any] | None = None,  # values as accepted by add_response
        cache: LLMCache | None = None,
        rejected_keys: set[str] | None = None,
    ) -> None:
        super().__init__(cache)
        self._responses: dict[str, list[str]] = defaultdict(list)
        self.calls: list[tuple[LLMRequest, str]] = []
        self.rejected_keys = rejected_keys or set()
        self._responders: dict[str, Callable[[str], Any]] = {}
        self.add_response("verify_key", {"ok": True})
        for name, value in (responses or {}).items():
            self._responses.pop(name, None)
            self.add_response(name, value)

    def add_response(self, prompt_name: str, response: list[str] | str | Any) -> None:
        """Queue responses. Non-string values are JSON-encoded."""
        items = response if isinstance(response, list) else [response]
        for item in items:
            self._responses[prompt_name].append(item if isinstance(item, str) else json.dumps(item))

    def add_responder(self, prompt_name: str, responder: Callable[[str], Any]) -> None:
        """Answer `prompt_name` by calling `responder(prompt)` (for prompts whose ids vary per call).
        Queued responses for the same prompt take precedence."""
        self._responders[prompt_name] = responder

    async def _complete_json(self, request: LLMRequest, prompt: str, schema: dict[str, Any]) -> str:
        self.calls.append((request, prompt))
        if request.api_key in self.rejected_keys:
            raise LLMAuthError("fake: key rejected")
        if request.prompt_name in self._responders and not self._responses.get(request.prompt_name):
            return json.dumps(self._responders[request.prompt_name](prompt))
        queue = self._responses.get(request.prompt_name)
        if not queue:
            raise LookupError(f"FakeLLMClient has no recorded response for prompt {request.prompt_name!r}")
        return queue.pop(0) if len(queue) > 1 else queue[0]
