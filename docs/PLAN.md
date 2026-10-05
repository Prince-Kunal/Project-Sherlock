# Sherlock — Implementation Plan

> **Sherlock** is the project name. Use it for the repo (`sherlock/`), the app title in the UI, the Docker Compose project name, and the Google OAuth app name.

> **For Claude Code:** This is the source of truth for the project. Read it fully before starting.
> Work **one phase at a time**, in order. A phase is done only when every item in its
> **Acceptance criteria** passes. After each phase, update the **Progress log** at the bottom,
> then stop and summarize what was built before starting the next phase.
> If something here is ambiguous or conflicts with reality (e.g. an external API's response
> shape changed), stop and ask instead of guessing. The **Invariants** section is non-negotiable.

---

## 1. What we're building

A self-hosted web app that helps a small group of users (the owner + friends, < 20 people) get
referrals for jobs and internships. For each user it:

1. **Discovers** fresh job/internship openings (≤ 14 days old) from public ATS feeds and job APIs.
2. **Scores** each job against the user's resume and preferences; keeps only relevant ones.
3. **Finds a contact** at the company who could refer them (founder / eng manager / recruiter) and verifies their email.
4. **Tailors the resume** for the role by selecting/reordering/lightly rephrasing bullets from the user's master resume — never inventing anything.
5. **Drafts a short, personalised email** asking for a referral, with the tailored resume attached.
6. **Puts every draft in a review queue.** The user approves, edits, regenerates, or skips.
7. **Sends approved emails** from the user's own Gmail, spaced out under a daily cap, tracks replies, and drafts one follow-up if there's no reply.

### Two outreach modes
- **Job-linked outreach** (steps 1–7 above): starts from a live opening and asks for a referral for that specific role.
- **Open outreach (prospecting):** starts from a *target profile* the user defines — contact roles (e.g. "Engineering Manager", "CTO"), industries, locations, company size, specific companies — and reaches people at matching companies **even when no opening is posted**. Rationale: when a job is posted, hundreds apply; when there's no posting, competition is far lower, and a contact who likes the email or resume can still pass it on within their network or to a team that's quietly hiring. The ask is different: not "refer me for role X" but "is your team taking interns / would you be open to a short chat / could you point me to the right person?"

Both modes share the same contact finding, tailoring, review queue, sending, caps, and tracking. Each user sets how their daily batch is split between the two (default 60% job-linked, 40% open outreach).

### Non-goals (do not build)
- No LinkedIn scraping or automation of any kind (ToS violation, gets accounts banned).
- No fully autonomous sending. Every email needs a human approval.
- No mass-mailing features (no CSV blasts, no sequences longer than 1 follow-up).
- No public sign-up. Access is invite/allowlist only.

---

## 2. Invariants (must hold in every phase)

1. **No email is ever sent without an approval record.** The sender must check `outreach.status == 'approved'` AND an `outreach_events` row of type `approved` by the owning user exists. Check this at send time, not only at approve time.
2. **The tailored resume may not contain anything absent from the master resume.** Enforced by the deterministic validator in Phase 4. If validation fails, the draft is not created; it's retried once, then marked `failed` with a reason.
3. **Daily send cap and suppression list are enforced at send time inside a DB transaction.** Never rely on the UI for this.
4. **One active outreach per (user, company)** at a time, and a **global contact cooldown**: the same contact email can't receive outreach from *any* user of the app more than once in 30 days (friends must not spam the same engineering manager).
5. **Users only see their own data.** Every query touching user data filters by `user_id`. Add tests for this.
6. **Secrets live in env vars.** OAuth refresh tokens are encrypted at rest (Fernet, key from env).
7. **All LLM output is parsed into Pydantic models.** Invalid output → retry once with the validation error included → then fail gracefully. Never pass raw LLM text into the DB or an email.
8. **Tests never hit real external APIs.** Every external service sits behind an interface with a fake implementation and recorded fixtures.
9. **Every outgoing email contains an opt-out line**, and a reply containing opt-out intent adds the sender to the suppression list.
10. **Open-outreach emails never claim or imply a specific opening exists.** The draft validator rejects phrases like "your opening", "the role you posted", or a job title framed as an existing vacancy when `campaign_type == 'open'`.
11. **Every resume PDF Sherlock produces must pass the ATS check (§6.1) before it can be attached to a draft.** A failing PDF blocks the draft (`failed`, reason `ats_check_failed`); never attach it anyway.

---

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend API | Python 3.12, FastAPI, Pydantic v2 | async throughout |
| ORM / migrations | SQLAlchemy 2.0 (async) + Alembic | |
| Database | PostgreSQL 16 + `pgvector` | embeddings stored in DB |
| Queue / scheduler | Redis 7 + ARQ | cron jobs + task queue |
| LLM | **Google Gemini API (free tier)** via the `google-genai` SDK, behind `LLMClient` interface; Anthropic as an optional second provider | `LLM_PROVIDER=gemini` (default) or `anthropic`. `LLM_MODEL_SMART` for tailoring/drafting, `LLM_MODEL_FAST` for parsing/scoring/classifying. See §3.1 |
| Embeddings | `sentence-transformers` (`BAAI/bge-small-en-v1.5`, 384-dim), local | behind `Embedder` interface; free |
| Resume rendering | Jinja2 → Typst source → `typst compile` → PDF | Typst binary installed in Docker image |
| Resume parsing | `pdfplumber` / `python-docx` for text, then LLM → `MasterResume` schema | |
| Contacts | Hunter.io API behind `ContactProvider` interface | Apollo as optional second provider |
| Email | Gmail API (`google-api-python-client`) | send + read threads |
| Frontend | Next.js (App Router), TypeScript, Tailwind, shadcn/ui, TanStack Query | |
| Auth | Auth.js (NextAuth) with Google provider; backend verifies session JWT | dev-login bypass in local env only |
| Tooling | `uv`, ruff, mypy, pytest, pytest-asyncio, respx; eslint, prettier | |
| Local dev | docker compose: postgres, redis, backend, worker, frontend | |

### 3.1 LLM provider strategy (free-tier first)

The project has no LLM budget, so it runs on Gemini's free tier. Design for that from day one:

- **Models.** Default `LLM_MODEL_SMART=gemini-flash-latest` and `LLM_MODEL_FAST=gemini-flash-lite-latest`. Before Phase 1, check Google AI Studio for which models currently have a free tier and their limits, and pin explicit model versions in `.env` (aliases can change underneath you). Pro models are not on the free tier — don't use them.
- **Bring your own key (BYOK).** Free-tier rate limits apply **per Google Cloud project**, so one shared key would be split across every user. Each user creates their own free key in Google AI Studio and pastes it in Settings; it's stored encrypted (`user_llm_keys`). Background jobs for a user use that user's key. The owner's key (`GEMINI_API_KEY`) is used only for shared work (HN parsing, company-level processing) and as a fallback during onboarding.
- **Rate limiting.** A Redis token bucket per API key, configured from env (`LLM_RPM`, `LLM_RPD`). On HTTP 429 / `RESOURCE_EXHAUSTED`: exponential backoff with jitter; if the daily quota is exhausted, defer the user's remaining pipeline work to the next day instead of failing it.
- **Fallback model.** If `LLM_MODEL_SMART` is rate-limited, tailoring and drafting may fall back to `LLM_MODEL_FAST` once; the deterministic validators (Phases 4 and 6) are what guarantee quality either way.
- **Spend fewer calls.** Score jobs and companies in **batches of 10 per request** (one JSON array response). Cache LLM results by hash of (prompt name + prompt version + inputs) in Redis for 7 days. Only call the LLM for items that survive the cheap filters (hard filters + embeddings). Embeddings stay local (bge-small), costing nothing.
- **Privacy on the free tier.** Google may use free-tier prompts and responses to improve its products, and human reviewers may read them. So: never send phone numbers, personal email addresses, or home addresses to the LLM. Strip `basics` from the resume before any prompt and re-insert them when rendering. Refer to contacts by first name and role only; never send contact email addresses. Show users a one-line notice about this when they add their key.
- **Provider-agnostic prompts.** Prompts are plain Markdown with a JSON output schema; use Gemini's structured output (`response_mime_type="application/json"` + `response_schema`) when available, and still validate with Pydantic (invariant 7). Switching `LLM_PROVIDER` must require zero code changes outside `services/llm/`.

---

## 4. Repository layout

```
sherlock/
├── CLAUDE.md                  # short: "Read docs/PLAN.md. Follow invariants. One phase at a time."
├── docs/PLAN.md               # this file
├── docker-compose.yml
├── .env.example
├── data/
│   └── companies_seed.csv     # name, domain, ats_type, ats_token, size_hint
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/              # config.py, db.py, security.py (fernet), auth.py, logging.py
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic schemas (API + LLM contracts)
│   │   ├── api/routes/        # profile, resume, jobs, matches, outreach, contacts, settings, auth
│   │   ├── services/
│   │   │   ├── llm/           # client.py, fake.py, prompts/*.md
│   │   │   ├── embeddings/    # embedder.py, fake.py
│   │   │   ├── sources/       # base.py, greenhouse.py, lever.py, ashby.py, adzuna.py, hn.py, manual.py
│   │   │   ├── matching/      # prefilter.py, rerank.py
│   │   │   ├── resume/        # parser.py, tailor.py, validator.py, render.py, ats_check.py, templates/
│   │   │   ├── contacts/      # base.py, hunter.py, fake.py, selector.py
│   │   │   └── email/         # drafter.py, gmail.py, fake_gmail.py, scheduler.py, replies.py
│   │   └── workers/           # arq settings + task functions
│   └── tests/
│       ├── fixtures/          # recorded API responses, sample resumes, sample JDs
│       └── ...
└── frontend/
    └── app/
        ├── (auth)/login
        └── (dashboard)/review, jobs, targets, tracker, profile, settings
```

---

## 5. Data model

All tables have `id` (UUID), `created_at`, `updated_at`. User-owned tables have `user_id` FK with an index.

**users** — `email` (unique), `name`, `is_admin`, `is_active`, `timezone` (default `Asia/Kolkata`).

**allowed_emails** — `email` (unique). Only these can sign in.

**user_preferences** — `user_id` (unique), `target_roles` text[], `employment_types` text[] (`internship`, `full_time`), `locations` text[], `remote_ok` bool, `company_stages` text[] (`startup`, `mid`, `large`), `min_fit_score` int (default 70), `max_job_age_days` int (default 14), `daily_draft_batch` int (default 8), `open_outreach_share` int 0–100 (default 40; % of the daily batch used for open outreach), `daily_send_cap` int (default 15, hard max 30), `followup_after_days` int (default 6), `send_window_start` time (09:30), `send_window_end` time (18:00), `paused` bool, `about_me` text (≤ 300 chars, used in drafts).

**master_resumes** — `user_id`, `version` int, `data` JSONB (`MasterResume` schema, §6), `is_current` bool, `source_file_path`. New version on every save; keep history.

**companies** — `name`, `domain` (unique, nullable), `ats_type` (`greenhouse|lever|ashby|none`), `ats_token`, `size_hint` (`startup|mid|large|unknown`), `employee_count` (nullable), `industry`, `hq_location`, `description` text, `website_text` text (cleaned About/careers/blog text, ≤ 8k chars), `website_fetched_at`, `embedding` vector(384) (from description + website_text), `last_polled_at`.

**prospect_targets** — the user's open-outreach target profile(s): `user_id`, `name` (e.g. "Bangalore fintech startups"), `contact_titles` text[], `industries` text[], `locations` text[], `company_sizes` text[], `include_companies` (company ids), `exclude_companies` (company ids), `is_active` bool. A user can have several.

**company_matches** — `user_id`, `company_id`, `prospect_target_id`, `score` int 0–100, `reasoning` text, `status` (`new|queued|contacted|hidden`), unique (`user_id`, `company_id`).

**user_company_blocks** — `user_id`, `company_id`.

**jobs** — `company_id`, `source` (`greenhouse|lever|ashby|adzuna|hn|manual`), `external_id`, `title`, `location`, `remote` bool, `employment_type`, `description_text`, `url`, `posted_at` (nullable), `first_seen_at`, `last_seen_at`, `is_active` bool, `dedupe_hash` (unique), `embedding` vector(384).
- `dedupe_hash = sha256(normalize(company_domain or company_name) + normalize(title) + normalize(location))`.
- Effective age = `posted_at` if present else `first_seen_at`.

**job_matches** — `user_id`, `job_id` (unique together), `embedding_score` float, `llm_score` int 0–100, `matched_skills` text[], `missing_skills` text[], `reasoning` text, `status` (`new|shortlisted|hidden|in_pipeline|expired`).

**contacts** — `company_id`, `full_name`, `title`, `email` (unique), `email_source` (`hunter|apollo|manual|pattern`), `verification_status` (`valid|accept_all|unknown|invalid`), `verified_at`, `role_category` (`founder|eng_manager|engineer|recruiter|other`), `last_contacted_at` (global, for cooldown).

**outreach** — `user_id`, `campaign_type` (`job|open`), `job_id` (nullable; required when `job`), `company_id` (always set), `company_match_id` (nullable; set when `open`), `contact_id`, `status` (see state machine §7), `subject`, `body`, `tailored_resume` JSONB, `resume_pdf_path`, `resume_diff` JSONB, `ats_keyword_coverage` JSONB, `personalization_source` text, `scheduled_at`, `sent_at`, `gmail_message_id`, `gmail_thread_id`, `replied_at`, `followup_count` int, `outcome` (`none|referred|interview|rejected|not_hiring`), `notes`, `failure_reason`.
- Partial unique index: one row per (`user_id`, `company_id`) across both modes where status not in (`closed`, `skipped`, `failed`).

**outreach_events** — append-only audit log: `outreach_id`, `user_id`, `type` (`drafted|edited|regenerated|approved|skipped|scheduled|sent|send_failed|reply_detected|followup_drafted|followup_sent|bounced|closed|outcome_set`), `payload` JSONB.

**suppression_list** — `email` (unique), `reason` (`opt_out|bounce|manual`), `created_at`. Global across users.

**oauth_tokens** — `user_id` (unique), `provider` (`google`), `encrypted_refresh_token`, `scopes`, `expires_at`, `needs_reauth` bool.

**user_llm_keys** — `user_id` (unique), `provider` (`gemini|anthropic`), `encrypted_api_key`, `verified_at`, `last_quota_exhausted_at`.

**usage_ledger** — `user_id`, `provider` (`gemini|anthropic|hunter|apollo|adzuna`), `operation`, `units`, `est_cost_usd`, `created_at`.

---

## 6. Core schemas (LLM contracts)

```python
class Bullet(BaseModel):
    id: str                  # stable, e.g. "exp1-b2"
    text: str
    skills: list[str]        # canonical lowercase skill names
    pinned: bool = False     # always include when the parent section is included

class MasterResume(BaseModel):
    basics: Basics           # name, email, phone, location, links[{label,url}]
    summary: str | None
    education: list[Education]    # id, institution, degree, field, start, end, gpa?, bullets
    experience: list[Experience]  # id, org, role, location, start, end, bullets
    projects: list[Project]       # id, name, link?, tech[], bullets
    skills: dict[str, list[str]]  # {"languages": [...], "frameworks": [...], "tools": [...]}
    achievements: list[Bullet]

class MatchResult(BaseModel):
    fit_score: int           # 0-100
    employment_type: Literal["internship", "full_time", "contract", "unknown"]
    matched_skills: list[str]
    missing_must_haves: list[str]
    reasoning: str           # <= 2 sentences

class TailorPlan(BaseModel):
    section_order: list[str]                  # e.g. ["experience","projects","skills","education"]
    selected_bullet_ids: list[str]            # ordered
    rephrasings: dict[str, str]               # bullet_id -> new text (optional per bullet)
    skills_to_show: list[str]                 # subset of master skills, ordered by relevance
    summary: str | None

class CompanyMatchResult(BaseModel):   # open outreach: user ↔ company fit
    fit_score: int           # 0-100
    angle: str               # 1 sentence: why this user fits this company/team
    reasoning: str           # <= 2 sentences

class ContactChoice(BaseModel):  # produced by selector.py, mostly rule-based
    contact_id: UUID
    rationale: str

class EmailDraft(BaseModel):
    subject: str             # <= 70 chars
    body: str                # <= 150 words, plain text, includes opt-out line
    personalization_source: str  # exact sentence from JD/company info the hook is based on
```

### 6.1 ATS-friendly resume requirements

Referrers often paste the attached resume straight into their company's applicant tracking system (ATS), so every PDF must parse cleanly by machine, not just look good to a human. The Typst template and renderer must follow all of these:

**Layout**
- Single column. No tables, text boxes, multi-column grids, sidebars, or floating elements for content.
- No images, icons, logos, photos, skill bars/ratings, or charts. Separators are plain horizontal rules at most.
- Contact details (name, phone, email, location, links) in the main body at the top — **not** in a page header/footer, which some ATS skip.
- One page (enforced in Phase 4).
- Margins 0.5–0.75 in; body font 10–11 pt; name 16–20 pt.

**Text**
- Standard section headings, exactly: `Education`, `Experience`, `Projects`, `Skills`, `Achievements` (omit empty ones). No creative headings like "Where I've been".
- A common, embedded font (e.g. Inter, Source Sans 3, Liberation Serif, or Charter) shipped in the Docker image; text must be real selectable text, never outlined.
- **Disable ligatures** (`#set text(ligatures: false)`) — otherwise "fi"/"fl" extract as single Unicode glyphs and words like "profile" break in parsers.
- Bullets use `•` or `-`. No emoji or decorative Unicode anywhere.
- Consistent dates, one format: `Jan 2025 – Present` (en dash, three-letter month).
- Each entry header on its own line in a predictable order: Role — Organisation, then Location · Dates.
- Links written out as visible text (`github.com/username`, `linkedin.com/in/username`), also hyperlinked. Never hide a URL behind a word like "GitHub" — many ATS drop link targets.
- Skills section is plain comma-separated lists per category (`Languages: Python, Go, TypeScript`).

**Keywords (job-linked mode)**
- When the user genuinely has a skill, use the **job description's spelling** of it in the tailored resume (JD says "PostgreSQL", master says "postgres" → print "PostgreSQL"). The canonical alias map (`data/skills_aliases.json`) makes this safe: only aliases of skills the user already has may be swapped in. Never add skills the user lacks (invariant 2).
- Compute an **ATS keyword coverage** score: share of the JD's must-have skills that appear verbatim in the tailored resume text. Show it on the review card ("ATS match: 9/12 must-haves") with the missing ones listed — those are genuine gaps, not something to paper over.

**File**
- PDF/A-friendly output with document metadata: Title = `<Full Name> — Resume`, Author = full name.
- Filename sent to recruiters: `Firstname_Lastname_Resume.pdf` (no company name in the filename).

**Automated ATS check (`services/resume/ats_check.py`)** — runs on every rendered PDF:
1. Extract text with both `pdfplumber` and `pdftotext` (poppler).
2. Fail if any extraction contains `(cid:` sequences, ligature code points (U+FB00–U+FB06), or replacement characters (U+FFFD).
3. Fail if the name, email, and phone aren't found in the first 15% of the extracted text.
4. Fail if section headings don't appear in the extracted text in the rendered order.
5. Fail if any rendered bullet's text (whitespace-normalised) isn't found in the extraction — catches broken reading order or wrapped columns.
6. Fail if the PDF has more than 1 page, contains images, or has no text layer.
7. Report (don't fail) the keyword coverage score.

---

## 7. Outreach state machine

```
drafting ──► pending_review ──► approved ──► scheduled ──► sent ──► replied ──► closed
   │              │  ▲                            │          │
   │              │  └── (edit/regenerate)        │          └─► followup_due ─► (new draft goes to pending_review as a follow-up)
   │              └──► skipped                    └─► send_failed ─► pending_review (with reason)
   └──► failed (tailoring/validation/contact failure, with failure_reason)
```
- Transitions live in one module (`services/email/state.py`) with a `transition(outreach, to_status, actor)` function that validates the move and writes an `outreach_events` row. No other code sets `status` directly.
- A follow-up is a new draft on the same `outreach` row (`followup_count += 1`), sent as a reply in the same Gmail thread. Max 1 follow-up.
- A reply at any point after `sent` moves to `replied` and cancels pending follow-ups.

---

## 8. Background jobs (ARQ cron)

| Job | Schedule | What it does |
|---|---|---|
| `poll_sources` | every 6h | poll every company's ATS + aggregator queries, upsert jobs, mark unseen jobs inactive after 3 missed polls |
| `embed_new_jobs` | after `poll_sources` | compute embeddings for jobs missing one |
| `match_jobs_for_users` | after embedding | per active user: prefilter + LLM rerank new jobs, write `job_matches` |
| `discover_prospect_companies` | daily | per active `prospect_targets` row: find companies matching industries/locations/sizes via the company-search provider; upsert `companies`; fetch website text for new ones |
| `match_companies_for_users` | after discovery | score new (user, company) pairs → `company_matches` |
| `build_daily_drafts` | daily 07:00 user tz | per active, non-paused user: fill `daily_draft_batch` (minus drafts already pending), split by `open_outreach_share` between top job matches and top company matches; if one side runs short, the other fills the gap; run contact → tailor → draft pipeline |
| `schedule_and_send` | every 5 min | for approved items: assign `scheduled_at` inside send window with 3–12 min jitter, respecting daily cap; send those due |
| `check_replies` | every 30 min | poll Gmail threads of sent items; detect replies, bounces, opt-outs |
| `create_followups` | daily 08:00 | for `sent` items older than `followup_after_days` with no reply and `followup_count == 0`: draft follow-up → `pending_review` |
| `expire_matches` | daily | mark matches for jobs older than `max_job_age_days` or inactive as `expired` |

All tasks must be **idempotent** (safe to re-run) and must log a summary line (counts processed / succeeded / failed).

---

## 9. Phases

Each phase lists **Goal**, **Tasks**, and **Acceptance criteria**. Don't start a phase until the previous one's acceptance criteria all pass.

---

### Phase 0 — Foundations

**Goal:** Running skeleton with DB, queue, auth stub, and CI.

**Tasks**
- [ ] Monorepo layout as in §4. `CLAUDE.md` at root pointing to this doc.
- [ ] `docker-compose.yml` with postgres (pgvector image), redis, backend, worker, frontend. `.env.example` with every variable from §11.
- [ ] Backend: FastAPI app, settings via `pydantic-settings`, async SQLAlchemy session, Alembic configured, `/health` endpoint checking DB + Redis.
- [ ] Models + initial migration for **all tables in §5** (enable `vector` extension).
- [ ] ARQ worker boots with a no-op cron job.
- [ ] Auth stub: `DEV_AUTH=true` enables `POST /auth/dev-login` that issues a session for a seeded user. All routes take `current_user` from a dependency. (Real Google auth comes in Phase 7.)
- [ ] Interfaces + fakes: `LLMClient`, `Embedder`, `ContactProvider`, `GmailClient`, `JobSource`. Fakes return deterministic data.
- [ ] `GeminiClient` implementing `LLMClient` (structured JSON output, per-key Redis token bucket, 429 backoff, response cache, PII-redaction helper) as described in §3.1. `AnthropicClient` can be a stub for now.
- [ ] Frontend: Next.js app with dashboard shell, the five tabs from the mockup (Review queue, Jobs feed, Outreach tracker, Profile and resume, Settings) as empty pages, API client with TanStack Query.
- [ ] Tooling: ruff, mypy (strict on `app/`), pytest; eslint/prettier; a `Makefile` with `make up`, `make test`, `make lint`, `make migrate`.
- [ ] GitHub Actions: lint + test on push.

**Acceptance criteria**
- `make up` starts everything; `/health` returns ok; frontend loads the shell and can dev-login.
- `make test` and `make lint` pass in CI.
- Test proves a request without a session gets 401.

---

### Phase 1 — Profile and master resume

**Goal:** A user can upload their resume, get it parsed into a structured, editable master resume, and set preferences.

**Tasks**
- [ ] `POST /resume/upload` (PDF or DOCX, ≤ 5 MB): extract text → `LLM_MODEL_FAST` with prompt `prompts/parse_resume.md` → `MasterResume`. Generate stable bullet IDs. Auto-tag each bullet's `skills` (LLM), normalised via a canonical skills map (`data/skills_aliases.json`, e.g. `"reactjs" → "react"`, `"postgres" → "postgresql"`).
- [ ] `GET/PUT /resume` — read and save the current version (saving creates a new version).
- [ ] `GET/PUT /preferences`.
- [ ] `PUT /settings/llm-key`: user pastes a Gemini API key; validate it with one tiny test call; store encrypted in `user_llm_keys`. Show the free-tier data-use notice from §3.1. Onboarding is blocked until a valid key is saved (or the owner's key is allowed as a temporary fallback via `ALLOW_OWNER_KEY_FALLBACK`).
- [ ] Frontend **Profile and resume** page: upload; editable sections; per-bullet text editor, skill tag chips (add/remove), "pinned" toggle; preferences form (roles, types, locations, remote, company stages, min fit score, max age, batch size, daily cap, send window, about-me).
- [ ] Resume render preview: implement `render.py` now (Jinja2 → Typst → PDF) using the full master resume and a template that follows **every rule in §6.1**. Implement `ats_check.py` (§6.1) in this phase too and run it on the preview; show pass/fail with reasons on the Profile page. `GET /resume/preview.pdf`.

**Acceptance criteria**
- Uploading 3 fixture resumes (in `tests/fixtures/resumes/`) produces valid `MasterResume` objects (using the fake LLM with recorded outputs in tests).
- Editing and saving creates version N+1; previous version retrievable.
- Preview PDF renders and is 1 page for the fixture resumes.
- `ats_check` passes for all fixture resumes, and fails on deliberately broken fixtures: a two-column PDF, a PDF with ligatures enabled, an image-only (scanned) PDF, and a PDF with contact details only in the header.
- Skill aliases normalise correctly (unit tests).

---

### Phase 2 — Job discovery

**Goal:** Fresh jobs from multiple sources land in the DB, deduplicated, with ages tracked.

**Tasks**
- [ ] `JobSource` interface: `async def fetch(company | query) -> list[RawJob]`, then `normalize(RawJob) -> JobIn`.
- [ ] Adapters (verify each endpoint's current response shape with one real call, save it as a fixture, then code against the fixture):
  - Greenhouse: `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` (no reliable created date → use `first_seen_at`; `updated_at` is informational only).
  - Lever: `GET https://api.lever.co/v0/postings/{company}?mode=json` (`createdAt` ms epoch).
  - Ashby: `GET https://api.ashbyhq.com/posting-api/job-board/{name}` (use `publishedAt` if present).
  - Adzuna (India): `GET https://api.adzuna.com/v1/api/jobs/in/search/{page}?app_id=&app_key=&what=&max_days_old=14` — query built from each user's `target_roles`; companies created on the fly (domain unknown until Phase 5).
  - HN "Who is hiring": latest monthly thread via Algolia HN API; parse top-level comments with `LLM_MODEL_FAST` into `JobIn` (company, role, location, remote, url, contact hints). Lower priority — do last in this phase.
  - Manual: `POST /jobs/manual {url}` → fetch page, extract text (readability), LLM-parse into `JobIn`.
- [ ] HTML → clean text for descriptions (strip tags, collapse whitespace, cap at 12k chars).
- [ ] Employment-type + remote detection: rules first (keywords like "intern", "internship", "remote"), LLM fallback during matching.
- [ ] Company registry: load `data/companies_seed.csv` (start with ~50–100 Bangalore/remote-friendly startups on Greenhouse/Lever/Ashby). Admin endpoint to add companies.
- [ ] `poll_sources` cron with per-host rate limiting (≤ 1 req/s per host), retries with backoff, and `last_polled_at`.
- [ ] Upsert by `dedupe_hash`; update `last_seen_at`; mark inactive after 3 missed polls.
- [ ] Frontend **Jobs feed** (unscored for now): table with title, company, location, age, source link; filters for age and type.

**Acceptance criteria**
- Each adapter has fixture-based tests for normalisation, including missing fields.
- Running `poll_sources` twice doesn't create duplicates (test).
- Jobs older than `max_job_age_days` are excluded from the feed.
- Manual URL add works for a Greenhouse and a Lever job page fixture.

---

### Phase 3 — Matching and scoring

**Goal:** Each user sees only relevant jobs, ranked, with an explanation.

**Tasks**
- [ ] `Embedder` implementation with bge-small; embed jobs as `title + first 2k chars of description`; embed user profile as `target roles + skills + selected bullet texts`. Cache user embedding per resume version.
- [ ] Hard filters first (cheap): employment type, location/remote, blocked companies, age.
- [ ] Prefilter: pgvector cosine similarity; keep top 50 per user per run above a floor (config `EMBED_MIN_SIM`, start at 0.35, tune later).
- [ ] Rerank: `LLM_MODEL_FAST` with `prompts/match.md` → `list[MatchResult]`, **10 jobs per request**. Input: user preferences + skills + condensed resume (no `basics`), and for each job its title + first 2k chars of description. Write `job_matches`. If one item in a batch fails validation, re-score only that item.
- [ ] Log LLM usage to `usage_ledger`.
- [ ] API: `GET /matches?status=&min_score=`, `POST /matches/{id}/shortlist`, `POST /matches/{id}/hide`, `POST /companies/{id}/block`.
- [ ] Frontend **Jobs feed** now shows fit score badge, matched/missing skills, reasoning on expand, shortlist/hide/block actions, and a "+ Add job URL" button.

**Acceptance criteria**
- Given fixture jobs (one clearly relevant, one clearly irrelevant, one wrong type) and a fixture user, the pipeline ranks them correctly (fake LLM with recorded outputs + real hard filters).
- Matching is incremental: re-running doesn't re-score already-scored (user, job) pairs.
- User A cannot see user B's matches (test).

---

### Phase 4 — Resume tailoring (with guardrails)

**Goal:** For a (user, job) pair, produce a tailored 1-page PDF that contains nothing not in the master resume.

**Tasks**
- [ ] `tailor.py`: `LLM_MODEL_SMART` with `prompts/tailor.md` → `TailorPlan`. Prompt rules: only select from given bullet IDs; rephrasing may reorder emphasis and use the JD's terminology **only for skills already in the bullet's `skills` list**; no new numbers, tools, or outcomes; keep bullets ≤ 2 lines.
- [ ] `validator.py` (deterministic, the important part):
  - every `selected_bullet_id` exists in the master resume; all `pinned` bullets of included sections are present;
  - every tech/skill token found in a rephrased bullet (match against the canonical skills lexicon + aliases) must be in that bullet's `skills` or the master `skills` set;
  - every number/percentage in a rephrased bullet must appear in the original bullet;
  - `skills_to_show ⊆` master skills;
  - rephrased text length ≤ 1.3× original.
  - On failure: return structured errors; tailor retries once with the errors in the prompt; second failure → `failed`.
- [ ] Render tailored resume via the Phase 1 template; enforce 1 page (if overflow: drop lowest-ranked non-pinned bullets and re-render, max 3 attempts).
- [ ] Apply the JD-spelling keyword rule from §6.1 (aliases of skills the user already has only), compute keyword coverage, store it on the outreach row (`ats_keyword_coverage` JSONB: score, matched, missing).
- [ ] Run `ats_check` on every tailored PDF; on failure, re-render once, then mark `failed` with `ats_check_failed` (invariant 11).
- [ ] `resume_diff`: list of `{bullet_id, change: "added|removed|reordered|rephrased", before, after}` vs the master.
- [ ] Store PDFs at `STORAGE_DIR/{user_id}/{outreach_id}/Firstname_Lastname_Resume.pdf` (the filename the recipient sees).
- [ ] Temporary endpoint + UI button on a match: "Preview tailored resume" (full pipeline wiring comes in Phase 6).

**Acceptance criteria**
- Validator unit tests cover each rule, including adversarial cases: an injected "Kubernetes" not in master → rejected; "improved latency by 40%" when original says 30% → rejected; unknown bullet ID → rejected.
- A valid plan renders a 1-page PDF; the diff is correct.
- The overflow-trimming loop is tested.
- Keyword rule test: JD says "PostgreSQL", master skill is "postgres" → tailored PDF text contains "PostgreSQL"; JD says "Kubernetes", user lacks it → it appears only in `missing`, never in the PDF.
- Every tailored PDF in the test suite passes `ats_check`.

---

### Phase 5 — Contact discovery

**Goal:** For a job, find the best person to email and a verified address.

**Tasks**
- [ ] Resolve company domain when missing (from job URL, ATS company page, or Hunter's company lookup). Store on `companies`.
- [ ] `ContactProvider` interface: `search_people(domain, titles) -> list[PersonCandidate]`, `find_email(domain, first, last) -> EmailResult`, `verify(email) -> VerificationStatus`.
- [ ] Hunter implementation (domain search with seniority/department filters, email finder, verifier). Apollo implementation optional behind the same interface.
- [ ] `selector.py` (rule-based, no LLM needed):
  - `size_hint == startup` (or ≤ 50 people): prefer founder/CTO → eng manager → recruiter.
  - otherwise: eng manager/team lead in a relevant department → recruiter → senior engineer.
  - skip contacts that are suppressed, `invalid`, or within the 30-day global cooldown.
  - Use HN "Who is hiring" contact hints first when the job came from HN.
- [ ] Only accept `valid` or `accept_all` verification (`accept_all` shows a warning badge in the UI).
- [ ] Cache: reuse contacts already in DB for the company for 60 days before calling the provider again. Log usage/credits to `usage_ledger`.
- [ ] `POST /outreach/{id}/contact` to manually set or swap a contact (with verification).

**Acceptance criteria**
- Selector tests: startup vs large company ordering, suppression, cooldown, invalid emails skipped.
- Provider calls are cached (second lookup for same domain within 60 days makes zero provider calls).
- When no contact is found, outreach goes to `failed` with reason `no_contact` and the UI offers "Add contact manually".

---

### Phase 6 — Drafting and the review queue

**Goal:** The daily pipeline produces reviewable drafts, and the review screen works end to end (without real sending yet).

**Tasks**
- [ ] `drafter.py`: `LLM_MODEL_SMART` with `prompts/draft_email.md` → `EmailDraft`. Inputs: job title, company, 2–3 key JD sentences, contact name/role, user's `about_me`, top 2 tailored bullets. Rules: ≤ 150 words, plain text, one concrete hook tied to `personalization_source` (must be a verbatim sentence from the JD or company text supplied — validate with a substring check), clear ask (referral or pointer to the right person), mention the attachment, sign-off with name + links, opt-out line (e.g. "If this isn't something you can help with, no worries — I won't follow up."). Tone differs slightly for founder vs recruiter vs EM.
- [ ] Draft validator: word count, subject length, opt-out present, no placeholder text like `[Company]`, `personalization_source` is a substring of provided context.
- [ ] Wire `build_daily_drafts`: match → contact (Phase 5) → tailor (Phase 4) → draft → `pending_review`. Each step failure → `failed` with reason; pipeline continues with the next job.
- [ ] API: `GET /outreach?status=`, `GET /outreach/{id}`, `PATCH /outreach/{id}` (edit subject/body), `POST /outreach/{id}/regenerate {hint?}`, `POST /outreach/{id}/approve`, `POST /outreach/{id}/skip`, `GET /outreach/{id}/resume.pdf`.
- [ ] Frontend **Review queue** (match the mockup): stat cards (new matches, sent this week vs cap, replies, follow-ups due); draft card with job title/company/age/source link, fit badge, matched/missing skills, contact block with verification status and "Change contact", editable subject + body, attachment row with "View diff" (side-by-side before/after bullets), PDF preview, and the ATS check result + keyword coverage ("ATS match: 9/12 must-haves", missing ones listed), buttons: Approve and send, Edit, Regenerate (with optional hint input), Skip. Keyboard shortcuts: `a` approve, `s` skip, `j/k` next/prev.
- [ ] "Manual pipeline" button on any shortlisted match: run contact → tailor → draft now.

**Acceptance criteria**
- End-to-end test with all fakes: seed user + jobs → `build_daily_drafts` → N drafts in `pending_review` (N ≤ batch size) → approve one → status `approved` + `approved` event exists.
- Editing creates an `edited` event and preserves the original text in the event payload.
- Draft validator tests (missing opt-out, too long, fake personalization source → rejected).

---

### Phase 7 — Google auth, Gmail sending, reply tracking

**Goal:** Real sign-in, real sending from the user's Gmail under all safety limits, and reply/follow-up handling.

**Tasks**
- [ ] Google Cloud project + OAuth consent screen (External, **Testing** mode; add friends as test users). Scopes: `openid email profile`, `https://www.googleapis.com/auth/gmail.send`, `https://www.googleapis.com/auth/gmail.readonly`.
  - Note: in Testing mode Google refresh tokens expire after ~7 days. Handle it: on `invalid_grant`, set `needs_reauth = true`, pause sending for that user, show a "Reconnect Gmail" banner. (Publishing the app with restricted Gmail scopes requires Google verification — out of scope for now.)
- [ ] Auth.js Google provider on the frontend; only `allowed_emails` can sign in; backend verifies the session JWT; store the encrypted refresh token in `oauth_tokens`. Keep `DEV_AUTH` for local only (refuse to start if `DEV_AUTH=true` and `ENV=production`).
- [ ] `gmail.py`: build MIME message (plain text body + PDF attachment), send via `users.messages.send`, store `gmail_message_id` + `gmail_thread_id`. Follow-ups are sent in-thread (`threadId` + `In-Reply-To`/`References` headers), no attachment.
- [ ] `scheduler.py`:
  - approved items get `scheduled_at` = next slot in the user's send window (weekdays only) with 3–12 min random gaps;
  - at send time, in one transaction with a row lock: re-check invariants 1, 3, 4 (approval event, daily cap by `sent_at` date in user tz, suppression, cooldown, user not paused, token healthy); then send; then set `sent`, update `contacts.last_contacted_at`.
  - on send error: `send_failed` → back to `pending_review` with reason.
- [ ] `replies.py` (`check_replies`): for each sent thread, fetch messages; a message from someone other than the user → `replied` (store snippet in event payload); a Mailer-Daemon/bounce → contact `invalid` + suppression (`bounce`) + outreach `failed`; opt-out phrases ("unsubscribe", "don't contact", "not interested", "remove me") → suppression (`opt_out`) + `closed`. Use `LLM_MODEL_FAST` only as a tiebreaker for ambiguous replies.
- [ ] `create_followups` cron as per §8; the follow-up draft is short (≤ 60 words) and goes through the same review queue.
- [ ] Frontend **Outreach tracker**: columns/filters for Scheduled, Sent, Replied, Follow-up due, Referred, Closed; row shows company, role, contact, sent date, last activity; detail drawer with the thread snippets, outcome selector, notes.
- [ ] Global banner when Gmail needs reconnecting or the user is paused.

**Acceptance criteria**
- With `FakeGmailClient`: approved → scheduled → sent; the cap blocks the (cap+1)th send in a day; suppressed contact never sends; unapproved item never sends even if its status is manually forced to `scheduled` (test invariant 1 directly).
- Reply, bounce, and opt-out detection tested with recorded Gmail thread fixtures.
- Manual test (document the steps in `docs/MANUAL_TESTS.md`): owner sends one real email to their own second address, receives it with the PDF attached, replies, and sees status flip to `replied` within 30 min.

---

### Phase 8 — Open outreach (prospecting mode)

**Goal:** Users can reach people at companies matching their target profile even when no job is posted, through the same review queue and sending pipeline.

**Tasks**
- [ ] Migration: `prospect_targets`, `company_matches`, new `companies` columns, `outreach.campaign_type` / `company_id` / `company_match_id`, `job_id` nullable (with a CHECK: `campaign_type = 'job'` ⇒ `job_id IS NOT NULL`). Backfill existing outreach as `job`.
- [ ] `CompanySearchProvider` interface: `search_companies(industries, locations, sizes, page) -> list[CompanyIn]`. Implement with Apollo organization search; fake + fixtures for tests. Also treat companies already in the DB (seed list, job feed) as candidates.
- [ ] Apollo `ContactProvider` implementation (people search by organization domain + titles). Contact lookup becomes a **waterfall**: cached DB contacts → Apollo → Hunter. Selector rules from Phase 5 still apply, filtered to the target's `contact_titles` first.
- [ ] Company website text: fetch homepage + /about + /careers + latest blog post if linked (respect robots.txt, 1 req/s per host, 10s timeout), clean to text, store in `website_text`. Embed companies.
- [ ] Company matching: hard filters (size, location, industry, excludes, blocked, company already contacted by this user in last 90 days) → embedding similarity between user profile and company → `LLM_MODEL_FAST` with `prompts/match_company.md` → `CompanyMatchResult`.
- [ ] Tailoring for open outreach: same `tailor.py` and validator, but the "job" input is a synthetic brief: target role(s) from the prospect target + company description + `angle`. Prompt variant `prompts/tailor_open.md`.
- [ ] Drafting for open outreach: `prompts/draft_open_email.md`. Hook must quote a sentence from `website_text`/`description` (same substring check as Phase 6). Ask variants by contact role: founder/CTO → "is the team open to an intern?"; EM → "would you be open to a 15-min chat or to passing my resume to whoever handles hiring?"; recruiter → "are there upcoming openings I should watch for?". Enforce invariant 10.
- [ ] Upgrade path: if a company with an open-outreach email in `sent` (no reply) later posts a job matching the user, the follow-up draft mentions the new opening and the outreach is re-labelled `job` with `job_id` set (event `upgraded_to_job`). Do not create a second outreach to that company.
- [ ] `build_daily_drafts`: implement the split from §8.
- [ ] Frontend:
  - new **Targets** tab: create/edit prospect targets (title chips, industry/location/size multi-selects, include/exclude companies), preview of matching companies with scores, hide/queue actions;
  - Review queue cards show a mode badge (**Job-linked** / **Open outreach**); open-outreach cards show the company angle and website hook source instead of the JD;
  - Settings: `open_outreach_share` slider;
  - Tracker: filter by mode; show reply rate per mode.

**Acceptance criteria**
- With fakes: a user with only a prospect target (no job matches) gets a full batch of open-outreach drafts; a user with both gets the configured split; when one side is short, the other fills.
- Validator rejects an open-outreach draft that says "the backend intern role you posted".
- Upgrade path test: a new matching job at a contacted company produces an in-thread follow-up mentioning the role, not a new outreach.
- Contact waterfall test: cached contact used first; Apollo called before Hunter; provider calls logged to `usage_ledger`.
- All invariants (§2) still pass, including one-active-outreach-per-company across both modes.

---

### Phase 9 — Multi-user hardening, settings, deployment

**Goal:** Safe to hand to friends.

**Tasks**
- [ ] Admin page (owner only): manage `allowed_emails`, see per-user usage and costs from `usage_ledger`, add companies to the registry, view the global suppression list.
- [ ] Per-user monthly quotas (`MAX_CONTACT_LOOKUPS_PER_USER_MONTH`, `MAX_LLM_USD_PER_USER_MONTH`); when exceeded, skip that user in `build_daily_drafts` and show a notice.
- [ ] **Settings** page: pause switch, daily batch size, daily send cap (≤ 30), send window, follow-up delay, Gmail connection status + reconnect, delete my data (hard delete user rows + files + revoke token).
- [ ] Data-isolation test suite: for every API route, user B gets 404 for user A's resources.
- [ ] Structured logging (JSON) with `user_id` and `outreach_id` context; Sentry (optional, env-gated).
- [ ] Rate limiting on API routes (simple Redis token bucket).
- [ ] Deployment: single VPS or Railway/Fly with managed Postgres + Redis; Docker images for backend/worker/frontend; HTTPS; nightly `pg_dump` backup; `docs/DEPLOY.md`.
- [ ] Onboarding flow for a new friend: sign in → connect Gmail → upload resume → review parsed resume → set preferences → first run.

**Acceptance criteria**
- Isolation suite passes for all routes.
- A second test user can go through onboarding end to end on the deployed instance.
- Quota exceeded → no provider/LLM calls made for that user (test).

---

### Phase 10 — Nice-to-haves (only after Phase 9)

- Outcome analytics: reply rate by contact role, company stage, email variant; weekly summary email to each user.
- A/B test two draft styles per user and surface which one gets more replies.
- More sources: Wellfound, YC Work at a Startup (only via allowed APIs/feeds), Cutshort/Instahyre if they offer feeds.
- Company research snippet (from the company's own site/blog) to improve the personalization hook.
- Chrome extension: "Send to Sherlock" button on any job page (uses the manual URL endpoint).
- DOCX export of the tailored resume (some older ATS parse Word better than PDF), passing an equivalent text-extraction check.
- Warm-path hints: alumni/shared-college flag if the user uploads a list of their connections (CSV export they own).

---

## 10. Prompt files

Keep prompts in `backend/app/services/llm/prompts/*.md`, versioned in git, loaded by name. Each prompt file has: purpose, inputs, output schema (JSON), hard rules, 1–2 examples. Required prompts: `parse_resume.md`, `tag_skills.md`, `parse_job_page.md`, `parse_hn_comment.md`, `match.md`, `match_company.md`, `tailor.md`, `tailor_open.md`, `draft_email.md`, `draft_open_email.md`, `draft_followup.md`, `classify_reply.md`. All prompts ask for **JSON only** and are parsed with Pydantic (invariant 7).

---

## 11. Environment variables

```
ENV=development|production
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
STORAGE_DIR=/data/files
FERNET_KEY=...
DEV_AUTH=true            # local only
AUTH_SECRET=...          # shared with Auth.js for JWT verification
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
LLM_PROVIDER=gemini
GEMINI_API_KEY=...       # owner's key: shared work + onboarding fallback
LLM_MODEL_SMART=gemini-flash-latest       # pin an explicit version after checking AI Studio
LLM_MODEL_FAST=gemini-flash-lite-latest   # pin an explicit version after checking AI Studio
LLM_RPM=8                # per key; set just under the free-tier limit for the chosen model
LLM_RPD=200              # per key; same
ALLOW_OWNER_KEY_FALLBACK=false
ANTHROPIC_API_KEY=       # optional, only if LLM_PROVIDER=anthropic
EMBED_MODEL=BAAI/bge-small-en-v1.5
EMBED_MIN_SIM=0.35
HUNTER_API_KEY=...
APOLLO_API_KEY=          # required from Phase 8 (company + people search)
ADZUNA_APP_ID=...
ADZUNA_APP_KEY=...
MAX_CONTACT_LOOKUPS_PER_USER_MONTH=40
MAX_LLM_USD_PER_USER_MONTH=5
SENTRY_DSN=              # optional
```

---

## 12. Testing strategy

- Unit tests for every pure function (normalisers, dedupe hash, validators, selector, scheduler slotting, state machine).
- Fixture-based tests for every external adapter (`tests/fixtures/<provider>/*.json`), using `respx` for HTTP mocking.
- Fake implementations for LLM/Embedder/Contacts/Gmail wired via dependency injection; an env flag `USE_FAKES=true` lets the whole app run locally with zero API keys (useful for UI work).
- One end-to-end test per phase from Phase 6 onward, all on fakes.
- Invariant tests are grouped in `tests/test_invariants.py` and must never be skipped.

---

## 13. Cost awareness

- Contact lookups are the scarcest resource (Hunter's free tier is small). Only look up contacts for jobs or companies that are about to be drafted, never for the whole feed or the whole company list.
- Open outreach consumes lookups faster than job-linked outreach (more companies, no posting to narrow the team). Company search results are cached for 30 days; people search results per company for 60 days.
- LLM cost is zero on Gemini's free tier; the real constraint is **requests per day per key**. Rough budget per user per day: ~6 batched scoring calls + ~2 calls per draft (tailor + email, plus occasional retries) × 8 drafts ≈ 25–30 requests. Keep it well under the per-key daily limit.
- Use the fast model for parsing/scoring, the smart model only for tailoring and drafting.
- If the group later gets budget (e.g. after someone lands an internship), switch `LLM_PROVIDER` or just the smart model for drafting; nothing else changes.
- Log every paid call to `usage_ledger`; show totals on the admin page.

---

## 14. Progress log

> Claude Code: append an entry after completing each phase.

| Phase | Status | Date | Notes / deviations from plan |
|---|---|---|---|
| 0 | done | 2026-10-04 | All 17 §5 tables (incl. Phase 8 ones) in the initial migration; enums are VARCHAR + named CHECK. Additions: `jobs.missed_polls` (for "inactive after 3 missed polls"), `upgraded_to_job` event type, `outreach.contact_id` nullable (`no_contact` failures), `outreach.job_id` FK is RESTRICT (jobs are deactivated, never deleted), CHECK `followup_count <= 1`. Host ports: Postgres 5433, Redis 6380 (5432/6379 taken locally). Frontend is Next 16 + shadcn `base-nova` (Base UI); `/api/*` is rewritten to FastAPI so the session cookie is first-party. Real Embedder/Hunter/Gmail raise `NotImplementedError` unless `USE_FAKES=true` until their phases. Gemini pinned to `gemini-3.8-flash` / `gemini-3.5-flash-lite`; set `LLM_RPM`/`LLM_RPD` from AI Studio. CI workflow written but not yet run (repo not pushed). |
| 1 | done | 2026-10-05 | Free tier observed in AI Studio: 5 RPM / 20 RPD **per model** (Gemini 2.5 Flash), so the limiter is per (key, model) and smart→fast fallback also covers daily-quota exhaustion. **Open concern for Phases 4/6:** ~18 usable smart-model requests/day vs. 8 drafts × (tailor + email) = 16 + retries; consider a default batch of 6 or one combined call. Fixture resumes are fictional (styled after 3 real student resumes; no real PII committed); recorded LLM outputs are real `gemini-3.5-flash-lite` responses to `parse_resume` v2 (`tests/fixtures/record_llm.py`). Email, phone and profile links are extracted deterministically (incl. hidden PDF/DOCX link targets) and never sent to the LLM. Additions: optional `start`/`end` on `Project`; LLM contract returns skills as `[{category, items}]`; endpoints `GET /resume/versions[/{n}]`, `GET /resume/ats-check`, `POST /resume/tag-skills`, `DELETE /settings/llm-key`; `timezone` in preferences. Template: A4, Source Sans 3 (OFL, vendored), ligatures + hyphenation off, PDF/A-2b, user text inserted as Typst string literals (no markup injection). ATS check: header-only contact is detected via PDF Artifact tags. Typst maps ligature glyphs back to "fi" on extraction, so the ligature fixture embeds U+FB0x code points (the real failure mode of pdfLaTeX/Word exports). `make up` now renews anonymous volumes so new Python deps reach the container. |
| 2 | done | 2026-10-06 | Greenhouse, Lever, Ashby and HN coded against real recorded responses (`tests/fixtures/record_sources.py`). **Deviation (agreed):** Greenhouse now returns `first_published`, used as `posted_at` (fallback `first_seen_at`); without it every old posting looked new on the first poll (live check: 1,333 of 8,710 jobs are ≤14 days). **Adzuna:** verified with a real call (`record_sources.py adzuna`; the app id is scrubbed from the fixture). Shape matched the docs; some titles arrive as UTF-8-read-as-Latin-1 mojibake, repaired by `fix_mojibake`. Poll skips Adzuna when `ADZUNA_APP_*` are unset. **HN:** the free tier can't parse a whole thread (~200–500 comments), so comments are keyword-prefiltered (default locations + users' locations), parsed 10 per request, ≤2 requests per poll, and processed ids kept in Redis so later polls continue; emails are extracted as contact hints before redaction (`jobs.source_meta`, new column). Manual URL add uses the Greenhouse/Lever/Ashby APIs directly (no LLM) and readability + `parse_job_page` for other pages. Seed: 56 verified boards (40 with India jobs, 16 remote-first). Poll: ≤1 req/s per host (in-process), retries with backoff, failed fetches don't count as misses, aggregator jobs age out instead of miss-tracking. Live poll: 56/56 boards, 8,710 jobs, 80 s. Extras: `GET/POST /admin/companies` (board verified on add), `POST /admin/poll`, `HN_ENABLED`. |
| 3 | not started | | |
| 4 | not started | | |
| 5 | not started | | |
| 6 | not started | | |
| 7 | not started | | |
| 8 | not started | | |
| 9 | not started | | |
| 10 | not started | | |
