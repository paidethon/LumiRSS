# 0017 — Reader Power UX & Unified Settings

> Status: **Completed** · Branch: `feat/0017-reader-power-ux-unified-settings`
> Baseline: 0016 completed (main, e6b931c).
> Owner model: DeepSeek V4 Pro (agent-plan/deepseek-v4-pro-ga-260813).
> Live AI smoke: not required (no AI surface changed); BFF/settings + UI verified
> end-to-end in Chromium (Playwright, desktop 1440/1920 + mobile 390/430,
> light + dark).

## Why

The Reader today offers only discrete typography presets (15/17/19/21px,
3 line-heights, 3 paragraph spacings, 3 widths) controlled from dropdowns,
and all settings are browser-local (`localStorage` key `lumirss-settings`)
with no durable home. 0017 replaces preset dropdowns with continuous
bounded controls (WeChat-Read-style), introduces one settings source of
truth shared by the Reader Aa panel and the Settings center, persists
portable preferences server-side in the existing `lumi.sqlite`
(`lumi_settings` allow-list store, 0015 foundation), migrates legacy local
values safely, and formalizes the experimental scroll-to-mark-read
behavior.

## Goal

1. Continuous numeric Reader controls: font size, line height, paragraph
   spacing, content width and page margin — WYSIWYG, keyboard accessible,
   instant, no "save" button.
2. One typed settings state shared by Reader Aa panel and Settings →
   Reading; one validation; one persistence path.
3. Local-first + server-durable: immediate local apply (Zustand + CSS
   variables) with a debounced, serialized server sync over a strict
   allow-listed PATCH API; safe localStorage → server migration.
4. scroll-to-mark-read formalized (default OFF, conservative conditions,
   manual-unread protection, no duplicate mutations).
5. Unified Settings IA: a dedicated Reading category; legacy browser-side
   translation provider settings retired honestly (0016 owns translation);
   no fake 0018 features.
6. Full automated tests (backend + frontend), real-browser integration and
   vision-model visual QA.

## User outcome

Drag a slider in the Reader Aa panel → the article reflows instantly.
Open Settings → Reading → the same numeric values are shown. Reload, or
open the app on another device → the same reading experience is restored
(server durable). Old discrete local settings (15/17/19/21 …) keep their
visual meaning after upgrade. No browser-side API keys remain anywhere
(translation runs through the 0016 BFF AI provider).

## Scope

- Reader typography: font size / line height / paragraph spacing / content
  width / page margin (new) — continuous sliders + A−/A+ steppers.
- Reader WYSIWYG via the existing CSS-variable pipeline
  (`--lumi-reader-*` on `<html>`); page margin gains mobile-safe clamps.
- Settings single-source: Zustand `useAppSettings` stays THE client store;
  Aa and Settings Reading consume it; server sync is a durability layer,
  never a UI-blocking one.
- `GET/PATCH/DELETE /api/v1/settings` (portable preferences) in the BFF
  over `lumi_settings` (reuse 0015 allow-listed KV + migration system).
- Legacy migration: old discrete Reader values map into the numeric schema;
  unknown/corrupt fields fall back to defaults (existing normalize).
- Legacy Translation Settings UI retired (0016 owns translation): stale
  provider/apiKey UI removed, backup envelope drops the now-pointless
  browser-side key encryption, old backups restore compatibly (keys
  ignored, never migrated anywhere).
- scrollMarkUnread: default OFF; conservative exit-upward condition +
  400 ms settle debounce + manual-unread suppression + duplicate guard.
- Settings IA: new `reading` category (typography, fonts, background,
  images, presets, Chinese typography, code highlight, scroll behavior,
  custom CSS/theme packs); appearance keeps app-level controls; AI page
  drops stale 0016 "planned" toggles.
- Tests: backend (defaults/round-trip/validation/reset/restart/malformed
  store/no-secret/no-RSS-shadow) + frontend (migration, WYSIWYG, sync
  debounce/race/reset/offline, same-source, scrollMarkUnread edge cases).
- Browser integration (Playwright) + vision QA (opencode-go/
  deepseek-v4-flash-vision-exp).

## Non-goals (unchanged boundaries)

- No second settings database, no `reader_settings.sqlite`; no settings in
  FreshRSS; no RSS-domain shadow state in lumi.sqlite.
- No multi-user / OAuth / social / recommendation / vector DB / Redis /
  Celery / n8n / WebDAV / production backup (0018) / deploy automation.
- No paged/dual-column reading modes in 0017 (evaluated → deferred, see
  below).
- No new translation architecture; no browser-side translation API keys;
  no secret ever through `/api/v1/settings`.
- No framework/tooling migration; no redesign of LumiRSS.

## Architecture decisions

### AD-0017-1 — Numeric ranges

Old discrete values are identity-mapped into continuous ranges so the
upgrade is visually non-breaking; ranges chosen from current Reader
typography, common Chinese long-form reading practice, the Lumi design
tokens, desktop pane widths (sidebar 240 + timeline 400 on 1440px), and
accessibility:

| Setting | Min | Default | Max | Step | Legacy map |
|---|---:|---:|---:|---:|---|
| Font size (px) | 12 | 17 | 28 | 1 | 15/17/19/21 unchanged |
| Line height | 1.2 | 1.85 | 2.4 | 0.05 | 1.65/1.85/2.05 unchanged |
| Paragraph spacing (em) | 0 | 0.85 | 2.0 | 0.05 | compact→0.5 · normal→0.85 · loose→1.25 |
| Content width (px) | 560 | 760 | 1080 | 20 | 680/760/900 unchanged |
| Page margin (px) | 12 | 32 | 64 | 4 | none → default 32 (current desktop px-8) |

Mobile constraints (CSS-level, independent of the stored number):

- content width: `max-width` semantics — on narrow viewports the article
  is already viewport-bound, so the numeric value cannot create
  horizontal overflow;
- page margin: clamped to 12–20 px on <1024px via
  `max(0.75rem, min(var(--lumi-reader-page-margin), 1.25rem))`
  (current mobile default 20px preserved).

### AD-0017-2 — One settings source of truth

```text
User input (Aa or Settings Reading)
  → useAppSettings.update(patch)        # single typed store
  → normalize + localStorage + CSS vars # immediate, synchronous
  → settings-sync (debounced 600ms)     # async durability layer
  → PATCH /api/v1/settings              # serialized, latest-wins
```

- TanStack Query is NOT used for settings state (settings are local-first
  UX state, not server query state); sync uses a small dedicated module
  with a serialized request queue.
- Server hydration: on startup GET settings; `stored=false` → local
  portable values become the migration seed (PUSH); `stored=true` →
  server values win EXCEPT keys the user already changed this session
  (dirty-keys protection prevents clobbering an active drag).
- Failures never roll the UI back (no toast spam; a silent retry on next
  change); final value flushed on `pagehide` (keepalive fetch).

### AD-0017-3 — Portable vs device-local classification

Server-durable (`lumi_settings` key `app.settings`, one JSON document,
`schemaVersion: 1`, strict allow-list — no per-key KV sprawl):

- themeMode, accentColor, uiFontStack, uiFontSize, reduceMotion;
- readerFontFamily, readerFontSize, readerLineHeight,
  readerParagraphSpacing, readerContentWidth, readerPageMargin,
  readerBackground, readerBackgroundCustom, readerJustify,
  readerImageMode, readerTextIndent, readerHangingPunctuation,
  readerChineseConversion, readerShowReadingTime, readerCodeHighlight,
  readerCodeTheme, scrollMarkUnread.

Device-local (never synced): sidebar/timeline layout, custom fonts
(IndexedDB ids/URLs), reader presets, custom CSS, filter rules/stats,
RSSHub instance list, timeline prefs (dimRead/groupByDate/unreadOnly/
timelineUnreadDot), language, bionic.

Secrets: none exist client-side after 0016; `/api/v1/settings` can never
read or write any secret.

### AD-0017-4 — scrollMarkUnread semantics (formal)

- Default OFF (unchanged).
- Mark-read only when: enabled AND row was fully visible (seen) AND row
  scrolled fully out above the viewport (bottom < 0) AND current read
  state is false AND not suppressed AND not already dispatched.
- 400 ms settle debounce after the exit event; re-entering the viewport
  cancels the pending mark.
- Manual-unread suppression: a read→unread transition observed in list
  data puts the entry in a suppressed set (no auto re-mark in the same
  scroll cycle); re-entering the viewport clears suppression (a new
  read-through cycle may mark again).
- Duplicate mutations prevented per session (dispatched set persists
  across list refreshes).

### AD-0017-5 — Settings IA

Categories (13 → 14): general · appearance · **reading (new)** ·
shortcuts · translation (retired → informational) · filters · rsshub ·
sources · ai · data · backup · services · workspace · about.

- appearance = app-level only (theme mode, accent, UI font/size, reduced
  motion);
- reading = all Reader controls incl. typography sliders, reset-reader
  action and scroll-to-mark-read;
- translation = honest note: translation is AI-based (0016), configure
  under AI; legacy provider page removed;
- ai = stale "planned 0016" toggles replaced by implemented-state notes.

### AD-0017-6 — Legacy translation settings retirement

- `TranslationSettingsPage` + `translationSettings` schema removed from
  the client settings model; `normalizeSettings` drops the old field
  (browser-side apiKeys are discarded on next normalization — never
  migrated into `lumi_settings`, never logged).
- Backup envelope: `encryptedSecrets`/`translationApiKeys` removed;
  importing an old backup ignores those fields compatibly.
- No new translation system is built (0016 BFF AI translation stays the
  only path).

## Gate checklist

- [x] Gate 0 — Repository reality audit
- [x] Gate 1 — Reader settings architecture audit
- [x] Gate 2 — Continuous reader controls (sliders + CSS + WYSIWYG)
- [x] Gate 3 — Unified settings persistence (server API + SQLite reuse +
      local-first sync + migration)
- [x] Gate 4 — Reader power UX (scrollMarkUnread formalization; reading
      position regression check)
- [x] Gate 5 — Unified settings UI (Reading category, Aa panel, reset,
      legacy translation retirement)
- [x] Gate 6 — Backend tests
- [x] Gate 7 — Frontend tests
- [x] Gate 8 — Browser integration (Playwright Chromium)
- [x] Gate 9 — Full regression (pytest 480 / web 522 / lint / build / git checks)
- [x] Visual QA (geometric, see notes) + fixes
- [x] Security + architecture review
- [x] Documentation closeout

## Results

- Backend: `services/bff/src/lumirss/app_settings.py` (strict pydantic
  `PortableSettings`/`PortableSettingsPatch`, allow-list, bounded numeric
  normalization, malformed/future-document fallback) + `main.py` routes
  `GET/PATCH/DELETE /api/v1/settings` (manual JSON parse so unknown key,
  wrong type, out-of-range and NaN/Infinity all return stable
  `400 invalid_app_settings`; no secrets). `tests/test_app_settings.py`
  (18 cases). Full backend suite: **480 passed**.
- Frontend: continuous numeric schema + legacy migration
  (`store/app-settings.ts`), `Slider` primitive (`components/ui/Slider.tsx`
  + slider/reader CSS), `store/settings-sync.ts` (local-first, 600ms
  debounce, serialized latest-wins PATCH, dirty-key hydration guard,
  keepalive pagehide flush, seed-on-first-visit), Aa panel rebuilt with 5
  sliders + A−/A+, new Settings → **阅读** category, Reader reset action,
  mobile-safe page-margin clamp. Legacy browser translation provider
  settings + `TranslationSettingsPage` retired (0016 owns translation;
  backup envelope no longer carries browser keys). scrollMarkUnread:
  400ms settle + manual-unread suppression + duplicate guard (a stray
  duplicate observer from the pre-0017 implementation was found and
  removed).
- Tests: `settings-sync.test.ts` (8), `scroll-mark-unread.test.tsx` (5),
  `slider.test.tsx` (4), migration/WYSIWYG/IA updates across existing
  specs. Full web suite: **522 passed** (43 files); `tsc -b` clean;
  `oxlint` exit 0 (pre-existing-style warnings only); `vite build` OK.
- Browser integration (Playwright, real Chromium): 19/19 smoke
  (WYSIWYG CSS-var updates, server seed + persistence, hydration on
  reload restoring server values, A−/A+ on mobile, validation 400s,
  no horizontal overflow) + 96/96 geometric visual-QA checks (all 5
  sliders in-viewport with usable width ≥120px and value readouts, reset
  present, modal no-overflow, dark theme) across 1920/1440 desktop and
  430/390 mobile, light + dark.

## Notes during execution

- Paragraph spacing step chosen as 0.05em (not 0.1) so the legacy
  default `0.85` and loose `1.25` stay exactly on-grid; snap is computed
  relative to `min` to avoid float drift.
- Vision-model screenshot QA: the dedicated vision provider was
  unreachable from the non-interactive CLI in this environment, so visual
  QA was performed deterministically via Playwright geometry/metrics
  (viewport containment, control reachability, value readouts, overflow,
  dark-theme tokens) plus screenshots captured under
  `/tmp/lumi0017/*.png`. All checks passed.
- Paged/dual-column reading and per-article scroll-position memory remain
  deferred (no existing prototype; out of scope).
