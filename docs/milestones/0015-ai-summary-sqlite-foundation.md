# 0015 — AI Foundation, Summary & Lumi SQLite Foundation

> Status: **In Progress** · Branch: `feat/0015-ai-sqlite-foundation`
> Created by Gate 0 (2026-09-02) from baseline `cb0e8b0` (main, 0014a merged).
> Owner model: DeepSeek V4 Pro (opencode-go/deepseek-v4-pro).

## Why

Lumi 至今没有任何 Lumi-owned 持久化：FreshRSS 拥有全部 RSS-domain 状态，
浏览器 localStorage 拥有全部 UI 偏好。0015 是第一个需要「Lumi 自己记住
东西」的里程碑（AI 生成结果、AI 配置、内容哈希缓存），因此必须先把
Lumi 的持久层边界立起来，再在其上做 AI 摘要。

The milestone is NOT merely "add an AI summary button". The real milestone
is: **establish the durable Lumi persistence and AI architecture on which
0016–0018 can safely build.**

## Goal

1. Activate `lumi.sqlite` as Lumi-owned application truth with a versioned
   migration system and safe connection lifecycle.
2. Persist Lumi server AI settings (non-secret) with typed, allow-listed keys.
3. Add ONE OpenAI-compatible AI provider abstraction (no SDK, no multi-provider
   routing, no fallback chains).
4. Implement on-demand article summary with a deterministic cache identity and
   explicit prompt version.
5. Expose a minimal summary API (`GET` never spends money; `POST` generates).
6. Turn the 0015 AI settings portion into real UI; integrate summary into the
   existing Reader (desktop + mobile) without redesigning the Reader.

## User outcome

Open an article → tap 「AI 摘要」 → concise Chinese summary appears (with
model/generation time), cached on reload (no second paid call). When AI is
not configured, the UI honestly says so and links to settings.

## Architecture

```text
                    lumi.sqlite（Lumi-owned truth）
                         ▲              ▲
         AI settings / summaries    （FreshRSS 数据绝不影子复制）
                         │
OpenAI-compatible endpoint ── AIProvider ── SummaryService ── BFF API
  (env API key, server-only)                        │
                                                    ▼
                                          React Web（只谈 BFF）
```

## Data ownership

- **FreshRSS** remains the RSS-domain source of truth (feeds, entries,
  subscriptions, categories, read/starred state, RSS metadata).
- **lumi.sqlite** owns Lumi application state only: AI generation/cache
  records + allow-listed non-secret server settings. It MUST NOT become a
  second RSS database — no feeds/entries/read/starred/subscriptions/category
  shadow tables.
- Valid Lumi AI records reference an opaque `entryRef` + store a
  `contentHash` for cache invalidation. That is not an RSS shadow copy.
- **RSSHub** stays upstream generator + independent runtime/config truth
  (unchanged in 0015).

## SQLite design

- Path: `LUMIRSS_DB_PATH` env var (pydantic-settings, lazy validation);
  default `<services/bff>/data/lumi.sqlite` (git-ignored via `data/` +
  `*.sqlite`). Tests always use temp DBs.
- Safety: `PRAGMA foreign_keys=ON`, `busy_timeout=5000`, `journal_mode=WAL`
  on every connection; connection-per-operation (no global cursor), sync
  sqlite3 wrapped in `asyncio.to_thread` (no new dependency).
- Versioned migrations: `lumirss/migrations/*.sql` applied in deterministic
  lexicographic order, exactly-once, each in its own transaction, recorded in
  `schema_migrations(version, applied_at)`. Failure never marks a migration
  complete; startup re-runs pending migrations idempotently.

### Initial schema (0015 scope only)

- `schema_migrations` — version, applied_at.
- `lumi_settings` — allow-listed key/value Lumi server settings
  (key TEXT PK, value TEXT, updated_at TEXT). 0015 registers only the
  non-secret AI keys: `ai.base_url`, `ai.model`, `ai.summary_language`.
- `ai_summaries` — entry_ref, content_hash, provider, model, prompt_version,
  language, status(not_generated|generating|success|failed), summary_text,
  failure_type, created_at, updated_at; UNIQUE on the full cache identity.

No speculative tables for 0016 chat / 0017 Reader settings / 0018 WebDAV.

## Migration strategy

Lightweight, stdlib-only, exactly-once, transaction-per-migration,
`schema_migrations` bookkeeping (no Alembic/SQLAlchemy/ORM). Applied lazily
on first storage use, idempotent across restarts.

## AI provider contract

```python
class AIProvider(Protocol):
    async def summarize(self, *, text: str, language: str) -> str
```

Direct OpenAI-compatible HTTP (`POST {base_url}/chat/completions`) over the
existing httpx stack. Configurable base URL + model (lumi.sqlite) + API key
(server env only). No SDK, no multi-provider routing.

- Timeouts bounded: connect 5s / read 60s.
- No retry of auth/invalid-request/model-not-found; no auto-retry loops.
- Stable Lumi errors: `ai_not_configured` (503), `ai_auth_error` (502),
  `ai_model_error` (502), `ai_rate_limited` (429), `ai_timeout` (504),
  `ai_invalid_response` (502), `ai_upstream_error` (502). Raw upstream
  bodies are never forwarded/logged.

## Summary domain

- Entry source: existing FreshRSSAdapter `get_entry` → `contentText`
  (already HTML→text normalized). Never refetch external websites.
- Normalization: whitespace-collapse + deterministic truncation at
  `MAX_SUMMARY_INPUT_CHARS = 12000`.
- Content hash: SHA-256 of the normalized text.
- Prompt version: `summary-v1` (participates in cache identity).
- Prompt-injection boundary: system prompt explicitly declares article text
  is untrusted source material, not instructions; no tools, no shell, no
  external actions.
- Output: plain text (UI renders as text, never unsanitized HTML).
- States: not_generated (no row) / generating / success / failed. Failed
  rows persist `failure_type` and explicit user retry re-calls the provider;
  successful exact cache hits never re-call. Stale `generating` rows (process
  died mid-call) are reported as failed(`interrupted`).
- Duplicate concurrent generation: in-process per-cache-key asyncio.Lock +
  DB UNIQUE identity (single-process BFF assumption documented).

## Cache identity

`(entryRef, contentHash, provider, model, promptVersion, language)` — exact
match = cache hit, zero provider calls. Changed content ⇒ different hash ⇒
different identity.

## Security

- API key: server env only; browser sees `configured: true/false` only.
- Key never logged; provider error bodies never logged/returned.
- GET summary never calls the provider (read-only FreshRSS + SQLite only).
- Article text bounded before reaching the provider.
- Prompt-injection boundary explicit; provider has no tools.

## In scope

Lumi SQLite foundation + migrations; persistent AI settings (provider/base
URL/model/summary language + configured flag); OpenAI-compatible provider;
cached article summary; summary API; AI settings UI; Reader summary UI;
Playwright desktop/mobile acceptance; Vision visual QA; full verification.

## Out of scope

Article/title translation (0016); AI conversation/chat (0016); Reader
typography sliders (0017); full Reader-settings server migration (0017);
WebDAV backup/restore + RSSHub Control Center (0018); secret vault;
multi-provider routing/fallback; background jobs/queues; speculative tables.

## Gate plan

```text
Gate 0  Spec + activation (this file, README/ROADMAP activation)
Gate 1  lumi.sqlite foundation + versioned migrations + temp-DB tests
Gate 2  Persistent Lumi AI settings (allow-listed, typed) + API
Gate 3  OpenAI-compatible provider (httpx, bounded, stable errors, fake for tests)
Gate 4  Summary domain + cache (normalize/hash/prompt-version/states/guard)
Gate 5  Summary API (GET cache-only / POST generate) + API tests
Gate 6  AI settings UI (Settings Center, desktop + mobile, no secret exposure)
Gate 7  Reader summary UI (all honest states, desktop + mobile)
Gate 8  Playwright behavioral acceptance (desktop 1440×900, mobile 390×844)
Gate 9  Vision visual QA (vision-review subagent, ≤2+1 screenshots)
Gate 10 Architecture + security review (git diff main...HEAD)
Final   Full BFF + Web tests, lint, build, docs closeout, local commit
```

## Acceptance criteria

See the Final Acceptance Matrix in the runbook; condensed:

```text
SQLITE    versioned migrations · restart idempotent · no shadow tables
AI        OpenAI-compatible abstraction · fake provider in tests · key server-only
SUMMARY   GET never generates · bounded input · contentHash · promptVersion
          cache identity full · exact hit no regeneration · retry after failure
WEB       AI settings (no secret) · Reader summary (all states) · desktop+mobile
VISUAL    desktop Reader + AI Settings + mobile Reader via Vision
VERIFY    full BFF / Web / lint / build / Playwright desktop + mobile
```

## Gate Progress

### Gate 0 — Spec + activation

- [x] Spec created; README/ROADMAP/dashboard activated 0015.
- Commit: `docs: activate milestone 0015`

### Gate 1 — Lumi SQLite foundation

- [x] `lumirss/storage.py` (Database: connection-per-operation, FK/busy_timeout/WAL, to_thread) + `lumirss/migrations.py` (versioned, exactly-once, transactional, schema_migrations) + `migrations/0001_initial.sql` (lumi_settings, ai_summaries + UNIQUE cache identity).
- [x] `LUMIRSS_DB_PATH` default `<services/bff>/data/lumi.sqlite` (git-ignored); `.env.example` updated.
- Tests: `tests/test_storage.py` — 8 passed (fresh migration / idempotent restart / version contiguity / cross-connection persistence / reopen / UNIQUE / CHECK / failed-migration rollback).

### Gate 2 — Server AI settings

- [x] `lumirss/ai_settings.py` — allow-listed typed keys (provider/base_url/model/summary_language), defaults in code, DB overrides only; `InvalidAiSettings` → 400.
- [x] `GET/PUT /api/v1/settings/ai` — `configured` derived from env `AI_API_KEY`, key never in responses.
- Tests: `tests/test_ai_settings.py` — 7 passed.

### Gate 3 — OpenAI-compatible provider

- [x] `lumirss/ai_provider.py` — narrow `AIProvider.summarize` protocol; direct chat/completions over shared httpx (connect 5s / read 60s); stable errors (ai_not_configured/auth/model/rate_limited/timeout/invalid_response/upstream); no raw body leaks; `summary-v1` system prompt with injection boundary.
- Tests: `tests/test_ai_provider.py` — 16 passed (zero network via MockTransport).

### Gate 4 — Summary domain + cache

- [x] `lumirss/ai_summary.py` — normalize (collapse + 12k bound), SHA-256 contentHash, cache identity (entryRef, contentHash, provider, model, promptVersion, language), states not_generated/generating/success/failed, stale-generating → interrupted, per-key asyncio.Lock + DB UNIQUE guard, failed rows persist failure_type, retry recovers.
- Tests: `tests/test_ai_summary.py` — 15 passed (cache-hit counter, hash/identity changes, failure/retry, concurrency == 1 call).

### Gate 5 — Summary API

- [x] `GET /api/v1/entries/{entryRef}/summary` (never generates) + `POST` (explicit generation); stable error mapping added.
- Tests: `tests/test_summary_api.py` — 7 passed; full BFF suite 420 passed.

## Completion notes

（Final Gate 后填写：DB path、schema version、API、UI、Vision、live smoke 等。）
