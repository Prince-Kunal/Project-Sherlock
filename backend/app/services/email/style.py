"""Phrasing that gives an email away as machine-written (PLAN.md Phase 6 follow-up).

People now spot LLM email patterns without trying: stock openers ("I came across", "As a third-year
student, …"), enthusiasm words, buzzwords, em dashes, and text lifted from the job posting or the
resume. `style_issues` finds them so the drafter can retry, and the review card can warn about any
that remain (or that the user's own edits introduce).
"""

import re

from app.schemas.outreach import DraftIssue

COPY_RUN = 8  # this many consecutive words taken from the posting or a resume bullet reads as pasted

# (pattern, what to tell the model). Case-insensitive, matched on word boundaries.
_TELLS: list[tuple[str, str]] = [
    (r"I hope (?:this|you)[^.]{0,30}(?:well|finds)", "a stock opener"),
    (r"I (?:came|stumbled) across", "a stock opener"),
    (r"I noticed (?:that )?\w+ (?:is|are) (?:looking|hiring|seeking)", "reading the posting back to them"),
    (r"I(?:'m| am) writing to", "a stock opener"),
    (r"I wanted to reach out|reaching out", "a stock phrase"),
    (r"(?:^|(?<=[.!?]\s))As an? (?!result\b|side\b|bonus\b|matter\b)[^,.\n]{3,60},", "the 'As a …,' opener"),
    (r"excited|thrilled|passionate|eager|keen to", "enthusiasm words"),
    (r"would (?:love|welcome) the (?:opportunity|chance)|unique opportunity|honou?red", "enthusiasm words"),
    (r"stood out|caught my (?:eye|attention)|resonate[sd]?|impressed (?:by|with)", "a stock phrase"),
    (r"(?:seeing|given) that (?:you|your)|since your (?:team|company)", "explaining the fit"),
    (r"this (?:seemed|seems|is) relevant|this (?:matches|lines up)", "explaining the fit"),
    (
        r"connects? (?:directly |well )?(?:to|with)|directly relevant|relevant experience",
        "explaining the fit",
    ),
    (r"hands-on experience", "a stock phrase"),
    (
        r"align(?:s|ed)? (?:well |perfectly |closely )?with|perfect fit|great fit|strong fit|well[- ]suited",
        "fit buzzwords",
    ),
    # Not "dynamic" or "robust": ordinary words in CS ("dynamic programming").
    (r"leverag\w*|delve|synerg\w*|cutting[- ]edge|innovative|fast[- ]paced|landscape|journey", "buzzwords"),
    (r"seamless\w*|invaluable|spearhead\w*|foster\w*|elevat\w*|empower\w*|showcas\w*", "buzzwords"),
    (r"hone[ds]? my|skill ?set|add value|make an impact|contribute to (?:your|the) team", "buzzwords"),
    (r"furthermore|moreover|additionally", "essay connectives"),
    (r"not only\b[^.]{1,60}\bbut also", "the 'not only … but also' construction"),
    (r"thank you for (?:your time|considering)|look(?:ing)? forward to hearing", "a stock closer"),
    (r"at your earliest convenience|(?:please )?don'?t hesitate|feel free to", "a stock closer"),
]
_TELL_RES = [
    (re.compile(rf"(?<![\w-])(?:{p})(?![\w-])", re.IGNORECASE | re.MULTILINE), why) for p, why in _TELLS
]
_DASH_RE = re.compile(r"[\u2014\u2013]| -- ")  # em dash, en dash
_SUBJECT_TELL_RE = re.compile(
    r":\s*(?:a\s+)?(?:referral|quick)\s+(?:request|question)\s*$|^quick question", re.I
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['\u2019][a-z]+)?")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def copied_run(text: str, sources: list[str], run: int = COPY_RUN) -> str | None:
    """The first `run`-word stretch of `text` that appears word for word in one of `sources`."""
    words = _tokens(text)
    grams: set[tuple[str, ...]] = set()
    for source in sources:
        tokens = _tokens(source)
        grams.update(tuple(tokens[i : i + run]) for i in range(len(tokens) - run + 1))
    for i in range(len(words) - run + 1):
        if tuple(words[i : i + run]) in grams:
            return " ".join(words[i : i + run])
    return None


def style_issues(subject: str, body: str, sources: list[str]) -> list[DraftIssue]:
    """Machine-sounding phrasing in an email. `sources` are texts it must not copy from (the job
    description and the resume bullets the email draws on)."""
    issues: list[DraftIssue] = []
    seen: set[str] = set()
    for pattern, why in _TELL_RES:
        if (match := pattern.search(body)) is not None:
            phrase = match.group(0).strip(" .!?,")
            if phrase.lower() not in seen:
                seen.add(phrase.lower())
                issues.append(
                    DraftIssue(
                        code="sounds_generated",
                        message=f"“{phrase}” is {why} that makes the email read as machine-written; "
                        "say it the way a person would, or leave it out.",
                    )
                )
    if _DASH_RE.search(body) or _DASH_RE.search(subject):
        issues.append(
            DraftIssue(
                code="sounds_generated",
                message="Don't use dashes as punctuation (em or en dashes); use a full stop or a comma.",
            )
        )
    if _SUBJECT_TELL_RE.search(subject.strip()):
        issues.append(
            DraftIssue(
                code="sounds_generated",
                message=f"The subject “{subject.strip()}” is a template; name the role plainly instead, "
                "e.g. “Backend intern role at Ledgerline”.",
            )
        )
    if (copied := copied_run(body, sources)) is not None:
        issues.append(
            DraftIssue(
                code="copied_text",
                message=f"“{copied} …” is copied from the job posting or the resume; retell it in your "
                "own words.",
            )
        )
    return issues
