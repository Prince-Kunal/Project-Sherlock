"""Pure helpers shared by job sources: HTML → text, employment type / remote detection, dedupe hash."""

import hashlib
import html
import re
import unicodedata
from typing import Literal

EmploymentType = Literal["internship", "full_time", "part_time", "contract"]

MAX_DESCRIPTION_CHARS = 12_000

_BLOCK_TAG_RE = re.compile(r"<\s*(br|/p|/div|/h[1-6]|/tr|/ul|/ol|/section|/article)\b[^>]*>", re.I)
# Inline tags vanish without adding a space ("<b>robots</b>." → "robots."); other tags become a space.
_INLINE_TAG_RE = re.compile(r"<\s*/?\s*(b|strong|i|em|u|span|a|code|small|sup|sub|mark)\b[^>]*>", re.I)
_LIST_ITEM_RE = re.compile(r"<\s*li\b[^>]*>", re.I)
_DROP_RE = re.compile(r"<\s*(script|style|noscript)\b.*?<\s*/\s*\1\s*>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(raw: str | None, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """Strip tags, keep paragraph/list structure as newlines, collapse whitespace, cap length.
    Handles double-encoded HTML (Greenhouse returns `&lt;p&gt;...`)."""
    if not raw:
        return ""
    text = html.unescape(raw) if "&lt;" in raw else raw
    text = _DROP_RE.sub(" ", text)
    text = _LIST_ITEM_RE.sub("\n- ", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _INLINE_TAG_RE.sub("", text)
    text = html.unescape(_TAG_RE.sub(" ", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return collapsed[:limit].rstrip()


_INTERN_RE = re.compile(r"\b(interns?|internships?|co-?op|apprentice(ship)?|trainee)\b", re.I)
_CONTRACT_RE = re.compile(r"\b(contract(or)?|freelance|temporary)\b", re.I)
_PART_TIME_RE = re.compile(r"\bpart[\s-]?time\b", re.I)
_FULL_TIME_RE = re.compile(r"\b(full[\s-]?time|permanent)\b", re.I)

_HINTS: dict[str, EmploymentType] = {
    "fulltime": "full_time",
    "permanent": "full_time",
    "regular": "full_time",
    "intern": "internship",
    "internship": "internship",
    "contract": "contract",
    "contractor": "contract",
    "temporary": "contract",
    "freelance": "contract",
    "parttime": "part_time",
}


def detect_employment_type(title: str, hint: str | None = None) -> EmploymentType | None:
    """Rules first (PLAN.md Phase 2): the title wins for internships, then the source's own field,
    then title keywords. None means unknown (the LLM decides during matching)."""
    if _INTERN_RE.search(title):
        return "internship"
    if hint:
        key = re.sub(r"[^a-z]", "", hint.lower())
        if key in _HINTS:
            return _HINTS[key]
    if _CONTRACT_RE.search(title):
        return "contract"
    if _PART_TIME_RE.search(title):
        return "part_time"
    if _FULL_TIME_RE.search(title):
        return "full_time"
    return None


_REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed)\b", re.I)


def detect_remote(
    location: str | None, workplace_hint: str | None = None, is_remote: bool | None = None
) -> bool | None:
    if is_remote is not None:
        return is_remote
    if workplace_hint:
        hint = re.sub(r"[^a-z]", "", workplace_hint.lower())
        if hint == "remote":
            return True
        if hint in {"onsite", "hybrid", "inoffice", "office"}:
            return False
    if location and _REMOTE_RE.search(location):
        return True
    return None


_CITY_SYNONYMS = {
    "bangalore": "bengaluru",
    "gurgaon": "gurugram",
    "bombay": "mumbai",
    "madras": "chennai",
    "calcutta": "kolkata",
    "new delhi": "delhi",
}


def normalize_key(value: str | None) -> str:
    """Lowercase, accent-free, punctuation-free, whitespace-collapsed; common city aliases unified."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    text = " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())
    for alias, canonical in _CITY_SYNONYMS.items():
        text = re.sub(rf"\b{alias}\b", canonical, text)
    return text


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    domain = domain.strip().lower()
    domain = re.sub(r"^[a-z]+://", "", domain).split("/")[0]
    return domain.removeprefix("www.") or None


def dedupe_hash(company_domain: str | None, company_name: str, title: str, location: str | None) -> str:
    """sha256(normalize(company_domain or company_name) + normalize(title) + normalize(location))."""
    company = normalize_domain(company_domain) or normalize_key(company_name)
    material = "|".join([company, normalize_key(title), normalize_key(location)])
    return hashlib.sha256(material.encode()).hexdigest()
