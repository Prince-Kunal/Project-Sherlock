"""Referral email drafting (PLAN.md Phase 6): smart model with prompts/draft_email.md → EmailDraft →
deterministic validator (one retry with the issues) → the final email.

The model writes only the middle of the email. The greeting ("Hi Priya,"), the opt-out line and the
signature (name + links) are added here, so the user's personal details never reach the LLM (§3.1)
and every email carries an opt-out line (invariant 9).
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.models import Company, Contact, Job
from app.models.enums import RoleCategory
from app.schemas.outreach import DraftIssue, EmailDraft
from app.schemas.resume import Basics
from app.services.email.style import style_issues
from app.services.llm.client import LLMClient
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.resume.skills import SkillLexicon, get_lexicon

log = logging.getLogger(__name__)

MAX_WORDS = 150  # greeting + body + opt-out line (the signature isn't counted)
MAX_EDIT_WORDS = 200  # a little slack for the user's own edits
MAX_SUBJECT = 70
MAX_CONTEXT_SENTENCES = 3
OPT_OUT_LINE = "If this isn't something you can help with, just let me know and I won't follow up."
# The parts added in code vary per contact, so two emails from Sherlock don't end identically.
OPT_OUT_LINES = [
    OPT_OUT_LINE,
    "No worries if this isn't your area. Just tell me and I won't follow up.",
    "If now isn't a good time or it's not something you can do, say so and I won't follow up.",
    "And if you'd rather not, that's completely fine. Just reply and I'll leave it there.",
    "If it's not something you can help with, a one-line reply is enough and I won't follow up.",
]
SIGN_OFFS = ["Thanks,", "Best,", "Cheers,"]
# Edits may reword the opt-out line, but some opt-out must remain (invariant 9).
_OPT_OUT_RE = re.compile(
    r"won'?t (?:follow up|email you again|contact you again|reach out again)|unsubscribe|"
    r"(?:don'?t|not) (?:want|wish) to hear from me|let me know (?:and|if) I'?ll stop|"
    r"I'?ll leave it (?:there|at that)",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r"\[[^\]\n]{1,40}\]|\{\{?[^}\n]{1,40}\}?\}|<[A-Za-z][A-Za-z _-]{0,30}>|\b(?:TODO|TBD|XXX|lorem ipsum)\b",
    re.IGNORECASE,
)
_ATTACHMENT_RE = re.compile(r"\battach|\benclos|\bresume\b|\bCV\b", re.IGNORECASE)
_GREETING_RE = re.compile(r"\A\s*(?:hi|hello|hey|dear)\b", re.IGNORECASE)
_SIGNOFF_RE = re.compile(r"\n\s*(?:best|regards|thanks|thank you|cheers|sincerely)[,!.]?\s*(?:\n.*)?\Z", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s*")
_WORD_RE = re.compile(r"[\w'\u2019-]+")

ROLE_TONE: dict[RoleCategory, str] = {
    RoleCategory.FOUNDER: "a founder: keep it very short and direct, they read a lot of these",
    RoleCategory.ENG_MANAGER: "an engineering lead: open with your most relevant technical work, briefly",
    RoleCategory.ENGINEER: "an engineer: peer to peer, specific about the tech, no formality",
    RoleCategory.RECRUITER: "a recruiter: name the role, say plainly why you fit, ask how best to apply",
    RoleCategory.OTHER: "someone who may not be hiring: ask them to point you to the right person",
}


class DraftError(Exception):
    """The draft failed validation twice; `reason` is stored as the outreach's failure_reason."""

    def __init__(self, reason: str, message: str, issues: list[DraftIssue] | None = None) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.issues = issues or []


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


# Curly quotes and dashes the model may use in place of the source's straight ones.
_PUNCT = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)


def _normalize(text: str) -> str:
    text = text.translate(_PUNCT)
    return re.sub(r"\s+", " ", text).strip().casefold()


def split_sentences(text: str) -> list[str]:
    sentences = []
    for part in _SENTENCE_SPLIT_RE.split(text):
        sentence = _BULLET_PREFIX_RE.sub("", part).strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def key_sentences(
    jd_text: str,
    skills: set[str],
    lexicon: SkillLexicon,
    limit: int = MAX_CONTEXT_SENTENCES,
) -> list[str]:
    """The JD sentences most worth a hook: the ones naming the most of the candidate's skills (`skills`
    are canonical names), earlier sentences first on ties. Returned in the JD's own order, PII-redacted."""
    candidates = [s for s in split_sentences(jd_text) if 30 <= len(s) <= 300 and not s.endswith(":")]
    scored = []
    for position, sentence in enumerate(candidates):
        overlap = len(set(lexicon.find_in_text(sentence)) & skills)
        scored.append((-overlap, position, sentence))
    chosen = sorted(scored)[:limit]
    return [redact_pii(s) for _, _, s in sorted(chosen, key=lambda item: item[1])]


def company_sentences(company: Company, limit: int = 2) -> list[str]:
    text = company.description or ""
    return [redact_pii(s) for s in split_sentences(text) if 30 <= len(s) <= 300][:limit]


def first_name(contact: Contact) -> str | None:
    name = (contact.full_name or "").strip()
    if not name or "@" in name or name.lower() == contact.email.split("@", 1)[0].lower():
        return None  # a name made from the address ("priya.n") isn't a name
    return name.split()[0].capitalize() if name.split()[0].islower() else name.split()[0]


def display_url(url: str) -> str:
    return re.sub(r"^https?://(?:www\.)?", "", url).rstrip("/")


def signature(basics: Basics) -> str:
    lines = [basics.name.strip()]
    links = [display_url(link.url) for link in basics.links if link.url][:3]
    if links:
        lines.append(" | ".join(links))
    return "\n".join(lines)


def _pick(options: list[str], key: str) -> str:
    return options[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(options)]


def opt_out_line(contact: Contact) -> str:
    return _pick(OPT_OUT_LINES, "opt-out:" + contact.email.lower())


def compose_body(draft: EmailDraft, contact: Contact, basics: Basics) -> str:
    sign_off = _pick(SIGN_OFFS, "sign-off:" + contact.email.lower())
    return (
        f"{greeting_for(contact)}\n\n{draft.body.strip()}\n\n{opt_out_line(contact)}\n\n"
        f"{sign_off}\n{signature(basics)}"
    )


def check_text(subject: str, body: str, *, max_words: int) -> list[DraftIssue]:
    """Rules for any email about to be reviewed or sent, including the user's own edits."""
    issues: list[DraftIssue] = []
    if not subject.strip():
        issues.append(DraftIssue(code="subject_empty", message="The subject is empty."))
    elif len(subject.strip()) > MAX_SUBJECT:
        issues.append(
            DraftIssue(
                code="subject_too_long",
                message=f"The subject is {len(subject.strip())} characters; keep it under {MAX_SUBJECT}.",
            )
        )
    if not _OPT_OUT_RE.search(body):
        issues.append(
            DraftIssue(code="no_opt_out", message="Keep an opt-out line, e.g. “" + OPT_OUT_LINE + "”")
        )
    for text in (subject, body):
        if (placeholder := _PLACEHOLDER_RE.search(text)) is not None:
            issues.append(
                DraftIssue(code="placeholder", message=f"Replace the placeholder {placeholder.group(0)!r}.")
            )
            break
    words = word_count(_without_signature(body))
    if words > max_words:
        issues.append(DraftIssue(code="too_long", message=f"{words} words; keep it under {max_words}."))
    return issues


def _without_signature(body: str) -> str:
    """Everything up to the sign-off ("Best," and what follows) isn't counted toward the length."""
    return _SIGNOFF_RE.sub("", body)


STYLE_CODES = {"sounds_generated", "copied_text"}


def validate_draft(
    draft: EmailDraft, contexts: list[str], composed: str, sources: list[str] | None = None
) -> list[DraftIssue]:
    """PLAN.md Phase 6 draft validator: length, subject, opt-out, placeholders, a personalisation
    source that is really one of the supplied sentences (a substring check), and no machine-sounding
    phrasing or text copied from `sources` (the job description and resume bullets)."""
    issues = check_text(draft.subject, composed, max_words=MAX_WORDS)
    issues += style_issues(draft.subject, draft.body, sources or [])
    source = _normalize(draft.personalization_source)
    if len(source) < 15 or not any(source in _normalize(c) for c in contexts):
        issues.append(
            DraftIssue(
                code="unknown_source",
                message="personalization_source must be copied word for word from one of the context "
                "sentences.",
            )
        )
    if not _ATTACHMENT_RE.search(draft.body):
        issues.append(
            DraftIssue(code="no_attachment_mention", message="Mention that the resume is attached.")
        )
    if _GREETING_RE.search(draft.body) or _SIGNOFF_RE.search(draft.body):
        issues.append(
            DraftIssue(
                code="greeting_or_signoff",
                message="Leave out the greeting and the sign-off; they are added automatically.",
            )
        )
    return issues


@dataclass
class DraftInputs:
    job: Job
    company: Company
    contact: Contact
    basics: Basics
    about_me: str
    highlights: list[str]  # the top tailored bullets, most relevant first
    skills: set[str]  # the candidate's canonical skills, for picking JD sentences
    hint: str | None = None


@dataclass
class DraftResult:
    subject: str
    body: str
    personalization_source: str
    contexts: list[str]
    style_warnings: list[str]  # phrasing still flagged after the retry; shown on the review card


def _feedback(issues: list[DraftIssue], previous: EmailDraft) -> str:
    lines = [f"- [{i.code}] {i.message}" for i in issues]
    return "\n".join(lines) + "\n\nYour previous draft:\n```json\n" + previous.model_dump_json() + "\n```"


class Drafter:
    def __init__(self, llm: LLMClient, lexicon: SkillLexicon | None = None) -> None:
        self._llm = llm
        self._lexicon = lexicon or get_lexicon()
        self._prompt = load_prompt("draft_email")

    def contexts(self, inputs: DraftInputs) -> list[str]:
        sentences = key_sentences(inputs.job.description_text, inputs.skills, self._lexicon)
        return sentences + [s for s in company_sentences(inputs.company) if s not in sentences]

    def variables(self, inputs: DraftInputs, contexts: list[str]) -> dict[str, Any]:
        contact = inputs.contact
        payload = {
            "job": {
                "title": inputs.job.title,
                "company": inputs.company.name,
                "location": inputs.job.location,
            },
            "context_sentences": contexts or [inputs.job.title],
            "recipient": {
                "title": contact.title or "unknown",
                "role": contact.role_category.value,
                "tone": ROLE_TONE[contact.role_category],
            },
            "about_me": redact_pii(inputs.about_me.strip()) or "(not provided)",
            "highlights": [redact_pii(h) for h in inputs.highlights[:2]],
        }
        return {
            "inputs": json.dumps(payload, ensure_ascii=False, indent=2),
            "hint": redact_pii(inputs.hint.strip()) if inputs.hint and inputs.hint.strip() else "(none)",
        }

    async def draft(self, inputs: DraftInputs, api_key: str | None) -> DraftResult:
        """A draft that passes the validator, with one retry carrying the issues found. If only
        phrasing issues remain after the retry, the draft is kept with them as warnings (the user
        reviews every email anyway, and a failed draft would waste the tailoring already done)."""
        contexts = self.contexts(inputs) or [inputs.job.title]
        variables = self.variables(inputs, contexts)
        sources = [inputs.job.description_text, *inputs.highlights]
        feedback = "(none)"
        issues: list[DraftIssue] = []
        for attempt in (1, 2):
            request = self._prompt.request(
                tier="smart", api_key=api_key, allow_fallback=True, feedback=feedback, **variables
            )
            draft = await self._llm.generate(request, EmailDraft)
            composed = compose_body(draft, inputs.contact, inputs.basics)
            issues = validate_draft(draft, contexts, composed, sources)
            if not issues or (attempt == 2 and all(i.code in STYLE_CODES for i in issues)):
                return DraftResult(
                    subject=draft.subject.strip(),
                    body=composed,
                    personalization_source=draft.personalization_source.strip(),
                    contexts=contexts,
                    style_warnings=[i.message for i in issues],
                )
            log.info("draft attempt %d rejected: %s", attempt, [i.code for i in issues])
            feedback = _feedback(issues, draft)
        raise DraftError("draft_validation_failed", "the email failed validation twice", issues=issues)


_GREETING_LINE_RE = re.compile(r"\A(?:Hi|Hello|Hey|Dear) [^\n,]{1,60},")


def greeting_for(contact: Contact) -> str:
    name = first_name(contact)
    return f"Hi {name}," if name else "Hi there,"


def replace_greeting(body: str, contact: Contact) -> str:
    """After a contact swap, greet the new person (only when the first line is still a greeting)."""
    return _GREETING_LINE_RE.sub(greeting_for(contact), body, count=1)
