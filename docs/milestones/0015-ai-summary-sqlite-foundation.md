# 0015 — AI Foundation, Summary & Lumi SQLite Foundation

> Status: **Completed** · Branch: `feat/0015-ai-sqlite-foundation`
> Created by Gate 0 (2026-09-02) from baseline `cb0e8b0` (main, 0014a merged).
> Completed by Final Gate (2026-09-02).
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

### Gate 6 — AI settings UI

- [x] `components/settings/AiSettingsPage.tsx` — Provider 固定展示、Base URL / Model / 摘要语言（PUT 只写非机密字段）、key 状态 banner（服务端环境变量，页面无任何 key 输入框）、保存/错误反馈；categories.tsx 的 AI 分类从 planned 占位改为真实配置 + 0016 planned 项。
- Tests: `ai-settings-page.test.tsx` — 4 passed（PUT 载荷不含 apiKey；configured banner；保存失败路径）。

### Gate 7 — Reader summary UI

- [x] `components/ReaderSummary.tsx` — not_generated/生成按钮、generating、success（纯文本渲染 + model·时间 + 缓存徽标）、failed（failureType 稳定文案 + 重试）、not_configured、content 不可用、loading 骨架；集成进 Reader（header 与正文之间），移动端复用同一组件。
- Tests: `ai-summary.test.tsx` — 6 passed（唯一 POST 计数、缓存命中零 POST、未配置/失败/不可用状态）。
- gate-b.test.tsx 更新为真实 AI 页断言；全量 Web 486 passed；lint 3 warnings（存量）；build 通过。

### Gate 8 — Playwright behavioral acceptance（真实运行服务）

- 重启 BFF（当前工作树，8000）；Vite 5173 为当前树。
- lumi.sqlite：`services/bff/data/lumi.sqlite` 创建、git-ignored、schema version 1（schema_migrations/lumi_settings/ai_summaries + cache identity index）、无 RSS shadow 表、BFF 重启后设置保留（PUT model → 重启 → GET 命中）。
- Desktop 1440×900：开文章 → AI 摘要卡 → 点击 → 诚实「AI 未配置」；设置 → AI：Provider 固定、Base URL/Model/摘要语言可见、无任何 key 输入框；保存 `https://api.example.com/v1` + `example-model` → 刷新 → 持久化；Reader 正常；添加来源（RSS/网站/RSSHub 三 tab）正常。
- Mobile 390×844：全屏 Reader + AI 摘要可达；未配置 alert 呈现；scrollWidth 390 无横向溢出；返回列表正常；订阅 → 添加来源正常；移动设置 AI 页正常（值持久化、无 key 输入）。
- Console：全程唯一 error 为未配置 POST 的 503 资源日志（预期行为），无应用错误。
- 无 AI_API_KEY → 无实时生成：Live AI smoke SKIPPED。

### Gate 9 — Vision visual QA

- 3 张截图（Reader desktop / AI Settings desktop / Reader mobile）发送
  `opencode run -m opencode-go/deepseek-v4-flash-vision-exp`（vision-review
  agent 未被 `opencode run` 发现——user-level agent 未注册进 CLI；按 runbook
  fallback 直接调用 Vision 模型）。
- Verdict: **PASS**（3 条 MINOR：AA 面板观感 = 0012 存量、卡片 vs 分隔线风格 =
  既有设置页一致模式、保存按钮层级 = 既有 secondary 惯例；均不构成缺陷，未改）。

### Gate 10 — Architecture + security review

- 全清单复核（git diff main...HEAD）：迁移版本化 ✓、temp-DB 测试 ✓、无 shadow
  表 ✓、GET 零生成 ✓、key 不出 BFF/不进日志/不进响应 ✓、输入 12k 上限 ✓、
  contentHash 正确 ✓、缓存身份全维度 ✓、超时有界 ✓、provider 错误无原始
  body ✓、prompt-injection 边界显式 ✓、输出纯文本渲染 ✓、无 Redis/Celery ✓、
  无 0016/0017/0018 功能 ✓。
- 加固：`AiSettingsUpdate` 增加 `extra="forbid"`（向设置存储走私 apiKey 之类
  未知字段 → 422）+ 测试。安全备注：BFF 无认证（既有单用户信任模型），AI
  base URL 与 FreshRSS 等既有平面同等暴露面；生产加固属 0018/0019 范围。
- docs/architecture/README.md §5.5/§7 AIProviderAdapter 标注 0015 实装状态。

### Final Gate — verification

```text
BFF:    uv run pytest — 421 passed（375 存量+0015 新 46：storage 8 / ai_settings 8 /
        ai_provider 16 / ai_summary 15 / summary_api 7 = 46 新增，含 1 条硬化后新增）
Web:    pnpm test — 486 passed / 38 files（476 存量 + 10 新增）
lint:   oxlint — 3 warnings（存量）0 errors
build:  tsc -b + vite build 通过（chunk-size 提示存量）
Playwright desktop 1440×900 + mobile 390×844 — 全流程通过（Gate 8）
Vision: PASS（desktop Reader / AI Settings / mobile Reader）
```

## Completion notes

- **DB path**: `LUMIRSS_DB_PATH`（默认 `<services/bff>/data/lumi.sqlite`，git-ignored）。
- **Migration mechanism**: stdlib-only runner（`lumirss/migrations/*.sql` 字典序、
  每迁移独立事务、`schema_migrations` 记账、失败回滚且不记账、重启幂等）；
  schema version **1**。
- **Tables**: `schema_migrations` · `lumi_settings`（allow-list：ai.provider /
  ai.base_url / ai.model / ai.summary_language）· `ai_summaries`（cache identity
  UNIQUE）+ 无任何 RSS shadow 表。
- **API**:
  - `GET/PUT /api/v1/settings/ai`（configured 仅报告 key 存在与否）
  - `GET /api/v1/entries/{entryRef}/summary`（只读缓存，绝不花钱）
  - `POST /api/v1/entries/{entryRef}/summary`（显式生成；精确命中零成本）
- **AI provider contract**: `AIProvider.summarize(text, language) -> str`；
  OpenAI-compatible chat/completions 直连（shared httpx，connect 5s / read 60s）；
  key 仅服务端 env `AI_API_KEY`。
- **Prompt version**: `summary-v1`（含注入边界声明）；输入 bound 12,000 字符
  （空白折叠 + 确定性截断）；contentHash = SHA-256(normalized)。
- **Cache identity**: (entryRef, contentHash, provider, model, promptVersion,
  language)；单进程 per-key asyncio.Lock + DB UNIQUE 防并发重复生成；失败行
  持久化 failure_type、显式重试恢复；stale generating → failed(interrupted)。
- **Summary UI**: Reader 内卡片（8 态全诚实呈现，纯文本渲染，缓存徽标）；
  AI 设置页（Provider 固定 / Base URL / Model / 摘要语言 / key 状态 banner）。
- **Live AI smoke**: SKIPPED — 无服务端 AI_API_KEY 配置（未配置 UX 已实测）。
- **Intentionally deferred**: 0016 翻译/对话、0017 Reader 连续控件与设置迁移、
  0018 WebDAV/Control Center；无 speculative 表；Provider 多路由/流式/agent 均未做。
