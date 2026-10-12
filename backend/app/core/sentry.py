"""Optional error reporting (PLAN.md Phase 9): Sentry is on only when SENTRY_DSN is set.

No personal data is sent: `send_default_pii` stays off (no IPs, cookies or request bodies), and events
are tagged with the ids from the log context (request, user, outreach), never email addresses.
"""

from typing import Any

from app.core.config import get_settings
from app.core.logging import current_log_context


def _tag_with_context(event: Any, _hint: Any) -> Any:
    tags = event.setdefault("tags", {})
    for key, value in current_log_context().items():
        tags.setdefault(key, value)
    return event


def init_sentry(component: str) -> bool:
    """`component` is "api" or "worker". Returns whether Sentry was started."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        server_name=component,
        send_default_pii=False,
        traces_sample_rate=0.0,
        before_send=_tag_with_context,
    )
    return True
