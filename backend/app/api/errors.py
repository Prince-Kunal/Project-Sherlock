"""Shared translation of service errors into HTTP responses with a stable `code` for the frontend."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status

from app.services.llm.client import (
    LLMAuthError,
    LLMConfigError,
    LLMOutputError,
    LLMQuotaExhaustedError,
    LLMRateLimitedError,
)
from app.services.llm.user_keys import LLMKeyRequiredError


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@contextmanager
def llm_errors() -> Iterator[None]:
    try:
        yield
    except LLMKeyRequiredError as exc:
        raise api_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "llm_key_required",
            "Add your Gemini API key in Settings first.",
        ) from exc
    except LLMAuthError as exc:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "llm_key_invalid",
            "Gemini rejected your API key. Check it in Settings.",
        ) from exc
    except LLMQuotaExhaustedError as exc:
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "llm_quota_exhausted",
            "Your Gemini daily quota is used up. It resets at midnight US Pacific time.",
        ) from exc
    except LLMRateLimitedError as exc:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "llm_busy",
            "Gemini is busy or rate-limited right now. Try again in a minute.",
        ) from exc
    except LLMOutputError as exc:
        raise api_error(
            status.HTTP_502_BAD_GATEWAY, "llm_bad_output", "The AI returned an unusable answer. Try again."
        ) from exc
    except LLMConfigError as exc:
        raise api_error(status.HTTP_503_SERVICE_UNAVAILABLE, "llm_not_configured", str(exc)) from exc
