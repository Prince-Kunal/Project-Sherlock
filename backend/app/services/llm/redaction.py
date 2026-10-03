"""PII redaction before anything is sent to an LLM (PLAN.md §3.1 'Privacy on the free tier').

Free-tier prompts may be read by humans, so: strip resume `basics` (re-inserted at render time) and
scrub email addresses and phone numbers from any free text.
"""

import re
from typing import Any

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 10+ digits allowing spaces, dots, dashes, parentheses and a leading +, e.g. +91 98765 43210, (415) 555-0100.
_PHONE_RE = re.compile(r"(?<![\w])\+?\(?\d[\d\s().-]{8,}\d(?![\w])")


def redact_pii(text: str) -> str:
    text = _EMAIL_RE.sub("[email]", text)

    def _phone(match: re.Match[str]) -> str:
        digits = sum(ch.isdigit() for ch in match.group(0))
        return "[phone]" if digits >= 10 else match.group(0)

    return _PHONE_RE.sub(_phone, text)


def strip_basics(resume: dict[str, Any]) -> dict[str, Any]:
    """Copy of a MasterResume dict without the `basics` block (name, email, phone, location, links)."""
    return {key: value for key, value in resume.items() if key != "basics"}
