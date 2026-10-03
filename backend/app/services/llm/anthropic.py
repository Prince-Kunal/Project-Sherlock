"""Optional second provider (LLM_PROVIDER=anthropic). Stub until there's a budget for it (PLAN.md §13)."""

from typing import Any

from app.services.llm.client import LLMClient, LLMRequest


class AnthropicClient(LLMClient):
    async def _complete_json(self, request: LLMRequest, prompt: str, schema: dict[str, Any]) -> str:
        raise NotImplementedError("AnthropicClient is not implemented yet; use LLM_PROVIDER=gemini")
