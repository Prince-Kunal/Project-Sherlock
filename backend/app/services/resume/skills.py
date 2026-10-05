"""Canonical skill names (PLAN.md Phase 1): aliases such as "ReactJS" or "postgres" map to one canonical
lowercase name ("react", "postgresql") using data/skills_aliases.json."""

import json
import re
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

_COMPACT_RE = re.compile(r"[\s._-]+")


def _key(skill: str) -> str:
    return " ".join(skill.lower().strip().strip(",;:").split())


def _compact(skill: str) -> str:
    return _COMPACT_RE.sub("", _key(skill))


class SkillLexicon:
    def __init__(self, canonical_to_aliases: dict[str, list[str]]) -> None:
        self.canonical: set[str] = set()
        self._exact: dict[str, str] = {}
        self._compact: dict[str, str] = {}
        for canonical, aliases in canonical_to_aliases.items():
            canonical = _key(canonical)
            self.canonical.add(canonical)
            for name in [canonical, *aliases]:
                self._exact.setdefault(_key(name), canonical)
                self._compact.setdefault(_compact(name), canonical)

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


@lru_cache
def get_lexicon() -> SkillLexicon:
    path = Path(get_settings().data_dir) / "skills_aliases.json"
    return SkillLexicon(json.loads(path.read_text(encoding="utf-8")))
