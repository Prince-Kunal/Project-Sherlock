# Sherlock

Read `docs/PLAN.md` first: it is the source of truth. Follow its **Invariants** (§2) without exception.
Work one phase at a time; a phase is done only when all its acceptance criteria pass. Update the
progress log (§14) after each phase.

- Backend: `backend/` (FastAPI, uv). Frontend: `frontend/` (Next.js 16, read `frontend/AGENTS.md`).
- `make up` runs everything in Docker; `make test` and `make lint` must pass before a phase is done.
- Host ports: Postgres 5433, Redis 6380, API 8000, frontend 3000.
- Tests never hit real external APIs: use the fakes in `app/services/*/fake*.py` and recorded fixtures.
- New external services go behind an interface in `app/services/` and are wired in `app/services/registry.py`.
