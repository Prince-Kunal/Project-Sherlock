# Prompts

One file per prompt, loaded by name with `load_prompt("<name>")` (see `prompt_loader.py`).

Every file starts with front matter holding a `version`. Bump it whenever the prompt's meaning changes:
the version is part of the LLM response cache key.

Each prompt contains: purpose, inputs, output schema (JSON), hard rules, and 1–2 examples. Prompts
ask for **JSON only**; output is always validated with Pydantic (invariant 7).

Never put personal contact details in a prompt: strip resume `basics` and run free text through
`redact_pii` first (PLAN.md §3.1).
