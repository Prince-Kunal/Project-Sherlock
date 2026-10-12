"""Logging setup (PLAN.md Phase 9): one line per record, JSON in production (`LOG_JSON`), with the
request, user and outreach the record belongs to.

Context lives in a ContextVar holding a dict: the API middleware opens a fresh one per request
(`request_id`), `current_user` and the path-id dependency add `user_id` / `outreach_id`, and worker
loops wrap each user and outreach in `log_context(...)`. Values are ids only, never email addresses.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings

_context: ContextVar[dict[str, str] | None] = ContextVar("log_context", default=None)

# Attributes every LogRecord has; anything else on a record came from `extra=` and is logged too.
_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "context"}


def current_log_context() -> dict[str, str]:
    return dict(_context.get() or {})


def bind_log_context(**values: object) -> None:
    """Add ids to the current context (the request's, or the enclosing `log_context`)."""
    clean = {k: str(v) for k, v in values.items() if v is not None}
    current = _context.get()
    if current is None:
        _context.set(clean)
    else:
        current.update(clean)  # mutated in place so the request's access line sees ids bound downstream


@contextmanager
def log_context(**values: object) -> Iterator[None]:
    """A nested scope: records inside it carry `values` on top of the enclosing context."""
    token = _context.set(
        {**(_context.get() or {}), **{k: str(v) for k, v in values.items() if v is not None}}
    )
    try:
        yield
    finally:
        _context.reset(token)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.context = current_log_context()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **getattr(record, "context", {}),
        }
        out.update({k: v for k, v in record.__dict__.items() if k not in _RECORD_ATTRS})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        context = getattr(record, "context", {})
        if context:
            line += " [" + " ".join(f"{k}={v}" for k, v in context.items()) + "]"
        return line


class _SherlockHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Marker type so configure_logging can replace its own handler when called twice."""


def configure_logging() -> None:
    settings = get_settings()
    use_json = settings.log_json or settings.env == "production"
    root = logging.getLogger()
    root.setLevel(logging.INFO if settings.env == "production" else logging.DEBUG)
    for handler in [h for h in root.handlers if isinstance(h, _SherlockHandler)]:
        root.removeHandler(handler)
    handler = _SherlockHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if use_json else TextFormatter())
    handler.addFilter(ContextFilter())
    root.addHandler(handler)

    # Third-party loggers are noisy at DEBUG.
    for name in ("httpx", "httpcore", "asyncio", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if use_json:
        # uvicorn and the arq CLI install their own plain-text handlers; route them through ours.
        for name in ("uvicorn", "uvicorn.error", "arq"):
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = True
    else:
        # The arq CLI installs its own handler; don't print its lines a second time via the root logger.
        logging.getLogger("arq").propagate = False
    logging.getLogger("uvicorn.access").disabled = True  # the request middleware logs each request
