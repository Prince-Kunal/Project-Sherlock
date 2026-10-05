"""Canonical skill names (PLAN.md Phase 1): aliases such as "ReactJS" or "postgres" map to one canonical
lowercase name ("react", "postgresql") using data/skills_aliases.json."""

import json
import re
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

_COMPACT_RE = re.compile(r"[\s._-]+")
# Skill names that are also everyday words ("go live", "spring 2025"): in free text they count as a
# skill only when capitalised ("Go", "Spring").
AMBIGUOUS_SKILLS = frozenset(
    {"c", "r", "go", "os", "rust", "ruby", "dart", "swift", "spring", "express", "flask", "make"}
)
# Word boundaries that respect "C++", "C#", ".NET" and "Node.js".
_BEFORE = r"(?<![\w+#.])"
_AFTER = r"(?![\w+#]|\.\w)"


def _key(skill: str) -> str:
    return " ".join(skill.lower().strip().strip(",;:").split())


def _compact(skill: str) -> str:
    return _COMPACT_RE.sub("", _key(skill))


class SkillLexicon:
    def __init__(self, canonical_to_aliases: dict[str, list[str]]) -> None:
        self.canonical: set[str] = set()
        self._exact: dict[str, str] = {}
        self._compact: dict[str, str] = {}
        self._aliases: dict[str, list[str]] = {}
        for canonical, aliases in canonical_to_aliases.items():
            canonical = _key(canonical)
            self.canonical.add(canonical)
            self._aliases[canonical] = [canonical, *(_key(a) for a in aliases)]
            for name in [canonical, *aliases]:
                self._exact.setdefault(_key(name), canonical)
                self._compact.setdefault(_compact(name), canonical)
        names = sorted(self._exact, key=len, reverse=True)  # longest first: "react native" before "react"
        self._text_re = re.compile(
            _BEFORE + "(" + "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names) + ")" + _AFTER,
            re.IGNORECASE,
        )

    def normalize(self, skill: str) -> str:
        """Canonical name for a known skill; otherwise the lowercased, whitespace-collapsed input."""
        key = _key(skill)
        return self._exact.get(key) or self._compact.get(_compact(skill)) or key

    def normalize_all(self, skills: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for skill in skills:
            if normalized := self.normalize(skill):
                seen.setdefault(normalized, None)
        return list(seen)

    def is_known(self, skill: str) -> bool:
        return self.normalize(skill) in self.canonical

    def aliases(self, canonical: str) -> list[str]:
        """Every known spelling of a canonical skill (lowercase), canonical first."""
        return list(self._aliases.get(_key(canonical), []))

    def find_in_text(self, text: str) -> dict[str, set[str]]:
        """Known skills mentioned in free text: canonical name → spellings as they appear."""
        found: dict[str, set[str]] = {}
        for match in self._text_re.finditer(text):
            spelling = match.group(1)
            canonical = self._exact[_key(spelling)]
            if _key(spelling) in AMBIGUOUS_SKILLS and not spelling[0].isupper():
                continue
            found.setdefault(canonical, set()).add(spelling)
        return found


def replace_skill_spelling(text: str, spellings: list[str], replacement: str) -> str:
    """Replace whole-word occurrences (any case) of `spellings` with `replacement`."""
    if not spellings:
        return text
    names = sorted({re.escape(s).replace(r"\ ", r"\s+") for s in spellings}, key=len, reverse=True)
    return re.sub(_BEFORE + "(" + "|".join(names) + ")" + _AFTER, replacement, text, flags=re.IGNORECASE)


@lru_cache
def get_lexicon() -> SkillLexicon:
    path = Path(get_settings().data_dir) / "skills_aliases.json"
    return SkillLexicon(json.loads(path.read_text(encoding="utf-8")))
