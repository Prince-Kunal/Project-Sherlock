"""Loads versioned prompt files from services/llm/prompts/<name>.md (PLAN.md §10).

File format:

    ---
    version: 1
    ---
    Markdown body with {{placeholders}}.

Placeholders are filled by `render`; non-string values are JSON-encoded. Every placeholder must be
supplied and every supplied variable must be used, so drift between code and prompt fails loudly.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.llm.client import LLMRequest, ModelTier

PROMPTS_DIR = Path(__file__).parent / "prompts"
_FRONT_MATTER_RE = re.compile(r"\A---\n(?P<meta>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    template: str

    @property
    def placeholders(self) -> set[str]:
        return set(_PLACEHOLDER_RE.findall(self.template))

    def render(self, **variables: Any) -> str:
        missing = self.placeholders - variables.keys()
        unused = variables.keys() - self.placeholders
        if missing or unused:
            raise ValueError(f"prompt {self.name}: missing={sorted(missing)} unused={sorted(unused)}")

        def _value(match: re.Match[str]) -> str:
            value = variables[match.group(1)]
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)

        return _PLACEHOLDER_RE.sub(_value, self.template)

    def request(
        self, *, tier: ModelTier, api_key: str | None = None, allow_fallback: bool = False, **variables: Any
    ) -> LLMRequest:
        return LLMRequest(
            prompt_name=self.name,
            prompt_version=self.version,
            prompt=self.render(**variables),
            tier=tier,
            api_key=api_key,
            allow_fallback=allow_fallback,
        )


def parse_prompt(name: str, text: str) -> Prompt:
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        raise ValueError(f"prompt {name}: missing front matter")
    meta = dict(line.split(":", 1) for line in match.group("meta").splitlines() if ":" in line)
    version = meta.get("version", "").strip()
    if not version:
        raise ValueError(f"prompt {name}: front matter needs a version")
    return Prompt(name=name, version=version, template=match.group("body").strip() + "\n")


@lru_cache
def load_prompt(name: str, directory: Path = PROMPTS_DIR) -> Prompt:
    path = directory / f"{name}.md"
    return parse_prompt(name, path.read_text(encoding="utf-8"))
