# 0016 — Translation & AI Conversation

> Status: **Completed** · Branch: `feat/0016-translation-ai-conversation`
> Baseline: 0015 completed (main, 4b6ff15).
> Owner model: DeepSeek V4 Pro (opencode-go/deepseek-v4-pro).
> Live AI smoke: SKIPPED — no server-side AI_API_KEY configured (unconfigured UX verified end-to-end).

## Why

0015 delivered the Lumi SQLite foundation, ONE OpenAI-compatible provider
abstraction and cached article summaries. 0016 extends that exact
foundation with the two remaining reader-AI capabilities: translating the
article being read, and asking questions about it. No new AI
infrastructure — the provider, the cache-identity pattern and the Lumi
persistence layer are reused as-is.

## Goal

1. Article translation with an explicit target language, cached exactly
   like summaries, presented as an Original/Translated view inside the
   existing Reader (never replacing the canonical article).
2. Article-scoped AI conversation (ask / follow-up / history persisted /
   reopen) grounded in the current article only.
3. Both flow through the ONE 0015 provider abstraction; secrets stay
   server-side; article text stays untrusted DATA.

## User outcome

Open an article → toggle 原文/译文 → translated title + body appear
(cached on reload). Tap 「AI 对话」→ side panel (mobile: full sheet) →
ask questions about the article → follow-ups keep article context →
close → the Reader is exactly where it was. When AI is not configured,
every entry point says so honestly and links to settings.

## Architecture

```text
FreshRSS (canonical RSS truth, never written by AI)
        │ get_entry → contentText
        ▼
Lumi BFF ── AIProvider (openai-compatible, env API key)
        │        ├── summarize   (0015)
        │        ├── complete()  (0016: generic chat/completions entry)
        │        │      ├── TranslationService   → ai_translations (cache)
        │        │      └── ConversationService  → ai_conversations + messages
        │        └──
        ▼
lumi.sqlite (Lumi-owned AI cache/conversation state only; no RSS shadow)
        │
        ▼
React Web (talks only to BFF; Original content always one tap away)
```

- `AIProvider` protocol gains ONE generic method `complete(messages)`.
  `summarize` (0015) delegates to it; translation and conversation build
  their own prompts on top. HTTP transport, error mapping, timeouts and
  secret handling stay in exactly one place.
- Prompt versions: `summary-v1` (0015), `translation-v1`, `chat-v1`.
- Streaming: NOT added. 0015 has no streaming and the milestone forbids
  parallel AI infrastructure; responses are reliable non-streaming calls.

## Data ownership (unchanged)

- FreshRSS remains the RSS-domain source of truth. Translations are
  NEVER written back; conversation never mutates FreshRSS.
- lumi.sqlite gains only Lumi-owned AI state: `ai_translations`
  (cache-identity rows) and `ai_conversations` / `ai_conversation_messages`
  (per-article conversation). No feed/entry/read/starred shadow tables.
- API key: server env only; browser learns `configured: true/false`.

## Backend work

- `ai_provider.py`: protocol + implementation gain `complete(messages)`;
  `summarize` refactored to delegate (no behavior change).
- `ai_settings.py`: allow-list gains `ai.translation_language`
  (default zh-CN; zh-CN | en); `PUT /api/v1/settings/ai` accepts
  `translationLanguage`; GET returns it.
- `migrations/0002_ai_translation_conversation.sql`:
  `ai_translations` (UNIQUE cache identity incl. target_language),
  `ai_conversations` (UNIQUE entry_ref+content_hash),
  `ai_conversation_messages` (FK → conversations, ON DELETE CASCADE).
- `ai_translation.py`: TranslationService — normalize (reuses 0015
  whitespace-collapse + 12000 bound on title+body), SHA-256 content hash,
  cache identity `(entryRef, contentHash, provider, model,
  promptVersion="translation-v1", targetLanguage)`, states
  not_generated/generating/success/failed, stale-generating →
  failed(interrupted), per-key lock + DB UNIQUE guard, failed rows keep
  failure_type, retry recovers. One provider call translates title+body
  with delimited output markers; missing markers degrade gracefully
  (body only, title stays original).
- `ai_conversation.py`: ConversationService — conversation keyed by
  (entryRef, contentHash) so changed article content naturally starts a
  fresh conversation; history bounded to last 12 messages; article
  context bounded (8k chars) + optional cached summary (2k); per-entry
  lock; question bounded 4k chars; provider errors map to existing
  stable errors; user question is NOT persisted on failure (input
  retained in UI for retry).
- `main.py` routes (all follow 0015 GET-read-only / POST-spends-money):
  - `GET/POST /api/v1/entries/{entryRef}/translation`
  - `GET /api/v1/entries/{entryRef}/conversation`
  - `POST /api/v1/entries/{entryRef}/conversation/messages`
    body `{ "question": "…" }` (typed, bounded).

## Frontend work

- `api/types.ts` / `client.ts` / `queries.ts`: translation +
  conversation types, fetchers and TanStack hooks following 0015
  patterns (GET query + POST mutation writing server state back into the
  query cache).
- `ReaderTranslation.tsx`: 原文/译文 segmented toggle above the article
  content; translated view renders translated title + plain-text body
  (whitespace-pre-wrap, never HTML); all states honest
  (loading/generating/success+cached badge/failed+retry/not_configured/
  content unavailable); original article always one tap away.
- `ArticleConversation.tsx`: right-side panel (Sheet side="right";
  mobile = full sheet) with article context header, message list
  (user/assistant bubbles, plain text), empty-state hints, loading
  skeleton, send pending state, inline error + retained input for retry,
  auto-scroll, Escape/backdrop close (Sheet primitive), focus trap.
- `ReaderHeader.tsx`: 「AI 对话」toolbar icon button (MessageSquare).
- `Reader.tsx`: wires conversation open/close; replaces the static
  ArticleContent block with ReaderTranslation (view state reset per
  entry via key).
- `ui/Sheet.tsx`: adds `side="right"` (already-designed but unused).
- `settings/AiSettingsPage.tsx`: adds 「翻译语言」select
  (zh-CN / en) and updates the money-rule footnote.

## Translation behavior

- Explicit target language from `ai.translation_language` (settings).
- One provider call per generation; exact cache hit = zero calls;
  changed content or changed target language = new identity.
- Original content is never replaced; FreshRSS never receives AI text.
- Reader clearly labels Original vs Translated via the segmented toggle.

## Conversation behavior

- Strictly article-scoped: title + source + bounded content (+ optional
  cached summary) as context; no global chat, no RAG, no tools.
- Follow-ups preserved server-side; reopening an article restores its
  conversation; article content change → fresh conversation.
- Reply language follows `ai.summary_language` (existing preference,
  no parallel setting).

## Security

- Prompt-injection boundary in every system prompt: article text is
  untrusted DATA, never instructions; no tools, no external actions, no
  shell; provider has no tool-calling payload.
- API key never leaves the BFF; provider error bodies never logged or
  forwarded; conversation/translation outputs rendered as plain text.
- Question/input sizes bounded; provider context bounded.

## Tests

- BFF: `test_ai_translation.py`, `test_translation_api.py`,
  `test_ai_conversation.py`, `test_conversation_api.py` (+ updates to
  `test_ai_settings.py` for the new key, `test_storage.py` for migration
  0002, provider tests for the `complete` refactor).
- Web: `ai-translation.test.tsx`, `ai-conversation.test.tsx` (+ update
  `ai-settings-page.test.tsx` for the translation-language field).

## Acceptance criteria

```text
TRANSLATION  GET never spends money · POST explicit · cache identity full
             target language explicit · original preserved · stale invalidation
             error/retry honest · reader shows Original|Translated
CONVERSATION article-scoped · follow-ups work · history persisted per article
             content change → new conversation · bounded context · honest errors
SECURITY     provider reused (no second abstraction) · no secret in browser
             injection boundary explicit · outputs plain text
WEB          desktop + mobile · no overflow · keyboard usable · Escape closes
             reader state survives open/close
VERIFY       full BFF · full Web · lint · build · git diff --check
```

## Non-goals

Global chat, multi-feed RAG, vector DB, embeddings, web search, tool
calling, streaming, WebSockets, multi-user, conversation dashboard,
Reader typography sliders (0017), WebDAV/Control Center (0018).

## Gate plan

```text
Gate 0  Spec + activation (this file, README/ROADMAP)
Gate 1  Backend: provider complete() + settings key + migration 0002
Gate 2  Backend: TranslationService + API + tests
Gate 3  Backend: ConversationService + API + tests
Gate 4  Frontend: translation UI + conversation panel + settings field
Gate 5  Integration: desktop + mobile behavioral pass
Gate 6  Visual verification (screenshots, Vision only if needed)
Final   Full BFF + Web tests, lint, build, docs closeout
```

## Gate Progress

### Gate 0 — Spec + activation

- [x] Spec created; branch `feat/0016-translation-ai-conversation` from main (4b6ff15).

### Gate 1 — Provider / settings / migration

- [x] `ai_provider.py`: `AIProvider.complete(messages)` (generic chat/completions entry); `summarize` delegates — one HTTP path, one error mapping.
- [x] `ai_settings.py`: allow-list gains `ai.translation_language` (zh-CN default); PUT/GET accept/return `translationLanguage`.
- [x] `migrations/0002_ai_translation_conversation.sql`: `ai_translations` (UNIQUE cache identity incl. target_language), `ai_conversations` (UNIQUE entry_ref+content_hash), `ai_conversation_messages` (FK CASCADE).

### Gate 2 — Translation domain + API

- [x] `ai_translation.py`: TranslationService — shared normalize/hash/stale/retry machinery from 0015; identity (entryRef, contentHash(title+body), provider, model, `translation-v1`, targetLanguage); delimited title/body output parsing with graceful fallback; states + failure persistence.
- [x] `GET/POST /api/v1/entries/{entryRef}/translation` (GET never spends; POST explicit).
- Tests: `test_ai_translation.py` (13) + `test_translation_api.py` (7).

### Gate 3 — Conversation domain + API

- [x] `ai_conversation.py`: ConversationService — per (entryRef, contentHash); bounded context (8k body + optional cached summary 2k) + bounded history (12) + bounded question (4k); injection boundary; nothing persisted on failure; per-entry lock.
- [x] `GET /api/v1/entries/{entryRef}/conversation` + `POST .../conversation/messages` (`{question}` typed, blank-strip 422).
- Tests: `test_ai_conversation.py` (12) + `test_conversation_api.py` (9).

### Gate 4 — Frontend

- [x] `ReaderTranslation.tsx`: 原文/译文 segmented toggle above the content; translated view = translated title + plain-text body (never HTML); honest states (skeleton / not_generated / generating / success+cached badge / failed+retry / not_configured / content unavailable); original one tap away.
- [x] `ArticleConversation.tsx`: right side panel via Sheet `side="right"` (mobile full sheet); article-context header, bubbles, empty-state examples, pending "正在思考", inline error + retained input, auto-scroll, Escape/backdrop/✕ close.
- [x] `ReaderHeader.tsx`: 「AI 对话」toolbar button; `Reader.tsx` wires panel + translation; unique sibling keys.
- [x] `Sheet.tsx`: `side="right"`; `AiSettingsPage.tsx`: 「翻译语言」select + money-rule footnote.
- Tests: `ai-translation.test.tsx` (5) + `ai-conversation.test.tsx` (8); `ai-settings-page.test.tsx` extended (5).

### Gate 5 — Integration (live FreshRSS, no AI key)

- [x] Desktop 1440×900: article → toggle 译文 → honest 503 「AI 未配置」+ retry → back to 原文 intact; AI 对话 panel opens with article context → send → inline error + input retained → Escape closes → reader intact; settings → AI shows 翻译语言.
- [x] Mobile 390×844: full-screen reader + toggle; full-sheet conversation (390×844 exact, no horizontal overflow, body scroll locked); Escape closes; scrollWidth == viewport.

### Gate 6 — Visual verification

- [x] 5 screenshots → `opencode run -m opencode-go/deepseek-v4-flash-vision-exp`.
- Verdict: PASS. Two flags reviewed and closed as non-defects: the "ghosted title" is the standard 30% translucent modal backdrop (existing dialog pattern), and the mobile error box measured 20→370px within the 390px viewport (no clipping).

### Final Gate — verification

- [x] BFF: full suite 462 passed (421 pre-0016 + 41 new: translation 13+7, conversation 12+9, settings/storage updated).
- [x] Web: full suite 499 passed (486 pre-0016 + 13 new); lint 3 warnings (pre-existing) 0 errors; `tsc -b && vite build` passed.
- [x] `git diff --check` clean; no commit/push.

## Completion notes

- **Translation API**: `GET/POST /api/v1/entries/{entryRef}/translation`; cache identity `(entryRef, contentHash, provider, model, translation-v1, targetLanguage)`; target from `ai.translation_language`; original article never modified; FreshRSS never receives AI text.
- **Conversation API**: `GET /api/v1/entries/{entryRef}/conversation` + `POST .../messages`; messages persisted per article version; failed sends persist nothing (input retained for retry).
- **Provider**: one generic `complete(messages)`; summarize delegates; no streaming, no tools, no second abstraction.
- **Settings**: `ai.translation_language` (zh-CN | en, default zh-CN); conversation replies follow `ai.summary_language`.
- **Intentionally deferred**: live AI generation smoke (no API key); streaming (not in 0015 foundation); 0017 Reader Power UX; 0018 Production/Ops.
