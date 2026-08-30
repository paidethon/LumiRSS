# LumiRSS Project State

> v6.4 — 0012 Reader Style Deep Customization active
> (spec approved 2026-08-30, from user 0012 directive; roadmap
> unchanged since the 0011 renumbering).

---

## 1. Executive status

LumiRSS has completed its initial RSS reader foundation through milestone
0008, and the UI/product-shell correction through milestone 0009:

- FreshRSS development environment + minimal RSSHub service;
- FastAPI BFF and FreshRSS adapter (feeds, entries, filters, cursor
  pagination, set-semantics state writes);
- React Web shell, real Reader, responsive Web / basic installable PWA;
- **0009 UI Reboot & Reference Lab**: Lumi Mist design system (semantic
  tokens, Light/Dark themes), 11 shared UI primitives, rebuilt
  Sidebar/Timeline/Reader at Folo-level density, Reader theme separation,
  Settings shell — with zero BFF changes and zero behavior regression.

The project is now at the **Lumi-native source control** stage.

Completed milestones:

```text
0009 — UI Reboot & Reference Lab          (completed 2026-08-29)
0010 — Settings Center & Adaptive Shell   (completed 2026-08-30, incl. 0010a)
0011 — Mobile UI Navigation & Five-Screen Alignment (completed 2026-08-30,
       incl. follow-up fix PR #18 rss-scope/category-tree)
0012 — Reader Style Deep Customization     (active spec)
```

AI Summary (renumbered from old 0009, four times) stays at milestone 0015.

---

## 2. Repository snapshot (locally verified)

```text
Repository:    https://github.com/paidethon/LumiRSS.git
Base branch:   main @ c4b84e9e4d09c080f44b99a17e35a241f27465fa
               (Merge PR #14 — 0008 complete; tree identical to 0acfc8e)
Work branch:   feat/0009-ui-reboot-reference-lab (created from main,
               user-approved)
License:       AGPL-3.0-only (LICENSE file added at the repo root,
               user-approved 2026-08-28)
Inspection:    2026-08-28
```

---

## 3. Milestone ledger

| Milestone | Status | Main outcome | v6 action |
|---|---|---|---|
| 0001 FreshRSS development environment | Implemented | Local FreshRSS service and API setup path | Preserve |
| 0002 BFF foundation | Implemented | FastAPI project, health and FreshRSS connection boundary | Preserve |
| 0003 Feed/entry read APIs | Implemented | Feeds, entry list/detail foundation | Preserve |
| 0004 State/filter/pagination | Implemented | read/star writes, filters and opaque cursor | Preserve |
| 0005 Web shell | Implemented | React three-pane shell wired to real BFF data | Refine visually |
| 0006 Reader | Implemented | sanitized detail reader and explicit state controls | Preserve/refine |
| 0007 Mobile + PWA | Implemented | responsive list/detail flow and static installability | Preserve/refine |
| 0008 RSSHub source expansion | Implemented | minimal RSSHub service and verified ingestion chain | Preserve |
| 0009 UI Reboot & Reference Lab | **Implemented** | design system, responsive shell, Folo/OrigRead audit | Completed 2026-08-29 |
| 0010 Settings Center & Adaptive Shell | **Implemented** | settings center, sidebar IA, adaptive panes, mobile tabs | Completed 2026-08-30 |
| 0011 Mobile UI Five-Screen Alignment | **Implemented** | AppSection + 四 tab 导航岛 + 五页面对齐 + rss-scope/category-tree 修复（PR #17/#18） | Completed 2026-08-30 |
| 0012 Reader Style Deep Customization | **Active** | 字体导入/中文排版/.lumitheme 主题包/Aa 面板/Shiki（docs/specs/0012-reader-style-deep-customization.md） | In progress |
| 0013 Unified Subscription Center | Planned | add/manage subscriptions inside Lumi; BFF-layer filtering + OPML | After 0012 |
| 0014 Source Discovery & RSSHub | Planned | URL/RSSHub discovery, route forms and preview; RSSHub instance testing | After 0013 |
| 0015 AI Foundation & Summary | Planned | on-demand summary, cache and safe status | Replaces old 0009 |
| 0016 Translation & AI Conversation | Planned | translation execution, test-connection, DeepL usage | After 0015 |
| 0017 Reader Power UX & Unified Settings | Planned | reading preferences, power navigation; server-side settings API; scroll-mark-read formalized | Later MVP |
| 0018 Production & Operations | Planned | Caddy, deployment, backup, diagnostics | Later MVP |
| 0019 MVP Stabilization | Planned | regression, docs, accessibility and release | MVP exit |

---

## 4. Current implemented backend surface

Verified by reading local source (`services/bff/src/lumirss/`):

```text
GET   /health/live
GET   /api/v1/feeds
GET   /api/v1/entries
GET   /api/v1/entries/{entryRef}
PATCH /api/v1/entries/{entryRef}/state
```

Verified behavior:

- `entryRef` is opaque (`e1.` + base64url, rejected before FreshRSS);
- cursor is opaque (`c1.` envelope with continuation + view + feedUrl
  scope; scope mismatch → 400 without touching FreshRSS);
- list supports views all/unread/starred and feed filtering, translated
  upstream (no post-filtering);
- list fields only — bodies are never in the list response;
- detail contains `contentText` (safe plain text) and `contentHtml`
  (untrusted upstream HTML, transported only);
- state writes use explicit set semantics with strict bool validation;
- ClientLogin/Action tokens stay in process memory with one-shot 401
  recovery;
- tests are fully mocked — no real secrets required.

### Backend gaps intentionally left for future milestones

- subscription control API (0013);
- OPML API (0013);
- RSSHub route catalog/preview API (0014);
- global search API (0011a candidate, user-approved honest-empty for now);
- unified settings API (0017);
- AI provider/cache/jobs (0015–0016);
- deployment authentication (0018);
- web clip/API/email/Obsidian connectors (Phase 2).

---

## 5. Current Web surface

Verified by reading local source (`apps/web/src/`):

- React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query, Zustand,
  DOMPurify (pnpm-managed; no UI primitive or icon library yet);
- desktop grid `240px 400px 1fr`, per-pane scrolling;
- one shared component tree; below 1024px (CSS only, no JS width
  detection) → Mobile Header + navigation drawer holding the same
  `<Sidebar />`, list↔reader driven by existing `selectedEntryRef`;
- Zustand holds only view / selectedFeedUrl / selectedEntryRef /
  mobileSidebarOpen; TanStack Query owns all server state;
- static PWA manifest + locally generated icons; no Service Worker, no
  offline claim;
- DOMPurify sanitization boundary in `ArticleContent` (single sanctioned
  `dangerouslySetInnerHTML`), `safeExternalHttpUrl` for the original
  link; opening an entry never marks it read.

### Current visual limitations (motivating 0009)

- only 8 CSS variables in `index.css`; components still contain
  hard-coded Tailwind colors (`bg-blue-50/60`, `hover:bg-gray-50`,
  `text-amber-500`);
- no light/dark theming, no semantic token system;
- no shared UI primitives (buttons/menus/popovers are ad-hoc);
- Timeline rows show only title/source/author/time — no favicon, excerpt
  or thumbnail hierarchy (current API does not supply those fields);
- Sidebar/Reader are functional but visually temporary.

These limitations are not permission to rewrite working behavior.

---

## 6. Current infrastructure

- FreshRSS 1.29.1 in Compose (127.0.0.1:8080, named volume);
- RSSHub official image pinned by digest
  (`diygod/rsshub@sha256:387fd32e…`, 127.0.0.1:1200, /healthz, memory
  cache — no Redis/Browserless/Chromium);
- verified non-RSS path: `/ithome/ranking/24h` → RSSHub → FreshRSS →
  BFF → Web Reader, with failure isolation (RSSHub stopped → stored
  entries still readable);
- BFF and Web run via local dev commands; Caddy/production remains
  planned (0018).

---

## 7. Documentation conflicts resolved by v6 (record)

- **Conflict A — next milestone**: v5 docs said 0009 = AI Summary.
  Resolved: 0009 = UI Reboot; AI Summary = 0012.
- **Conflict B — "FreshRSS is the only source of truth"**: now scoped to
  the RSS domain; Lumi owns settings/AI/future connector data.
- **Conflict C — "BFF never talks to RSSHub"**: now split into the read
  path (unchanged, never bypasses FreshRSS) and a planned control/catalog
  plane that may contact RSSHub for discovery/preview/health.
- **Conflict D — subscription workflow**: FreshRSS UI was the normal
  path in v5; v6 makes Lumi the normal UI, upstream UIs are escape
  hatches (delivered by 0010–0011).
- **Conflict E — spec list**: the old PROJECT_STATE spec list omitted
  `docs/specs/0007-mobile-pwa.md` (the file exists); v6 lists
  0001–0008 completely.

---

## 8. Known product decisions (user-approved)

- perform UI Reboot now, before adding AI;
- Folo is the primary UI interaction reference (interaction parity, not
  product parity);
- OrigRead Desktop is the secondary settings/source/reader reference;
- Lumi uses its own muted palette and pale blue-indigo accent;
- support light/dark/system themes and future custom accent;
- reader appearance is independent from app appearance;
- preserve responsive Web rather than building a native app in MVP;
- Lumi becomes the sole normal UI for FreshRSS/RSSHub-backed workflows;
- future knowledge-workbench connectors use a Lumi-owned unified layer;
- AI remains optional and must never block reading;
- **project license: AGPL-3.0-only** (approved 2026-08-28, enabling
  compliant adaptation of AGPL upstream references);
- reference baselines pinned in `docs/reference/UPSTREAMS.md`;
- source reuse recorded in `docs/reference/SOURCE_MAP.md`.

---

## 9. Immediate risks

- **UI scope explosion**: "implement all Folo features" is rejected;
  0009 is a presentation/system refactor, not a product clone.
- **Backend scope leak**: 0009 must not turn into source discovery,
  subscription API, AI or service-control implementation.
- **Private-data leakage**: logged-in Folo screenshots, browser profile
  data and personal subscription names must not enter Git (Gate 0 audit
  used computed styles only; zero screenshots captured).
- **Responsive regression**: desktop polish must not sacrifice the
  existing mobile list/reader flow.
- **Missing visual fields**: the current API provides no excerpt,
  thumbnail or favicon fields. 0009 must degrade gracefully and record
  contract needs instead of inventing browser-side scraping.

---

## 10. Completed work: 0010 + 0010a — Settings Center & Adaptive Shell

All gates user-approved (A/B/C/D: 2026-08-29–30; E/F/G (0010a): 2026-08-30).

### Delivered

- **Gate A — settings framework**: typed `app-settings` store
  (`store/app-settings.ts`: single localStorage key `lumirss-settings`,
  per-field normalization, legacy key migration from `lumirss-theme` /
  `lumirss-reader-bg`); `SettingItem` declarative renderer (title / toggle
  → Switch / enum → Select / action → Button / custom); `SettingsModal`
  (9-category left nav at Folo-measured metrics; blank-overlay / Escape /
  ✕ close — fixed a latent Dialog overlay-click bug from 0009).
- **Gate B — category pages**: keyboard shortcuts j/k/u/s
  (`lib/keyboard-shortcuts.ts`; genuine bug found & fixed: query cache key
  mismatch with `useEntries`); shortcuts cheatsheet page; data control
  (clear cache + reset settings, both real); about page (version / AGPL /
  repo / THIRD_PARTY_NOTICES); 4 planned pages (sources 0011/0012, AI
  0013/0014, services, workspace Phase 2) all disabled with milestone
  labels; unread-dot toggle wired to EntryRow (real).
- **Gate C — sidebar IA & adaptive panes**: Sidebar regrouped into
  信息来源 / 工作区 (9 Phase 2 items visible-but-disabled with badges);
  `PaneSeparator` (pointer drag with clamp 220–300 / 360–460, arrow-key
  ±10px, double-click reset, role=separator aria); collapse/expand for
  both panes; widths & collapse persisted (fixed a real separator
  height-collapse bug found only via live browser testing).
- **Gate D — mobile Folo-style + board + docs**: bottom tab bar
  (<768px: timeline / starred / settings, ≥44px + safe-area, hidden while
  reading); progress board revision (roadmap renumber + Lumi Mist light/dark
  unification + mobile overflow fix); PRD v6.1 / ROADMAP / PROJECT_STATE /
  AGENTS / README updates.
- **0010a Gate E — mobile settings redesign + IA + general**: fixed the
  broken <768 settings layout (missing `max-md:flex-col`) by replacing the
  Dialog+chips approach with a Folo-style full-screen settings page (grouped
  list → push subpages, shared CategoryPage components & store with desktop);
  categories 9 → 13 (translation / filters / rsshub / backup); general page
  additions (dimRead / groupByDate / unreadOnly / experimental
  scrollMarkUnread with badge).
- **0010a Gate F — appearance + reader style P0/P1 + OrigRead pages**:
  accent color picker (8 presets + custom, derived hover/pressed/soft),
  global UI font size (rem scaling) & font stacks, reduce motion, custom CSS
  editor with `.lumi-reader` prefixing (matchingClose bug found & fixed);
  reader font stacks ×4, background palette (paper/mint/custom hex +
  WCAG-adaptive text), paragraph spacing, justify, image modes; 5 built-in
  typography presets + derive/import/export; translation provider cards
  (microsoft/deepl/dlx), filter rules (CRUD + display-layer filtering +
  stats), RSSHub 16 built-in instances management, encrypted config backup
  (Web Crypto PBKDF2+AES-GCM; no-secret restore must not clear local keys —
  genuine bug found via live testing & fixed).
- **0010a Gate G — regression + docs**: backup round-trip live test 16/16
  (export encrypted → wrong-password reject → restore all → bad-file reject
  → no-secret restore keeps keys); viewport matrix 10/10; PRD v6.2 / ROADMAP /
  PROJECT_STATE / AGENTS / README / SOURCE_MAP / reader-style survey
  (docs/reference/reader-style-survey.md) / board renumber (0011 inserted,
  0012–0018 shifted).

### Verification (final numbers)

```text
Web tests:   208 passed (17 files; 162 pre-0010 + 46 new; zero regression)
Web lint:    0 errors, 1 warning (React Compiler note)
Web build:   success (js 317.42KB / gzip 99.36KB)
BFF tests:   121 passed, git diff -- services/bff empty
Live checks: drag 240→277 + reload restore; collapse/expand both panes;
             double-click reset; keyboard j/k/u/s in real browser;
             9 Phase-2 badges visible; mobile 390 zero overflow
Board:       Light/Dark + 1280/768/390 zero overflow, 0010 visible
```

---

## 10c. Completed work: 0012 — Reader Style Deep Customization

All gates executed 2026-08-30 (spec approved from user 0012 directive;
report submitted, awaiting user review before commit).

### Delivered

- **Gate 0**: spec 0012 + active-milestone docs revision (0011 →
  completed incl. PR #18, 0012 → active).
- **Gate 1**: 10 new reader settings fields inside the existing
  app-settings normalize/migration system (indent / hanging punctuation /
  S↔T conversion / reading time / code highlight + theme / bionic /
  custom-font id + URL reference).
- **Gate 2/3**: custom fonts — local WOFF2 (triple validation → IndexedDB
  → FontFace, content-hash dedupe, reload restore, delete-active fallback)
  and font URLs (http/https allowlist, remote FontFace, no local copy,
  structured CORS failure).
- **Gate 4**: Chinese typography (first-line indent scoped to top-level
  `p`; hanging punctuation behind `@supports`; OpenCC S↔T conversion
  display-layer only) + **new presentation pipeline security model**:
  raw HTML → inert DOM → controlled DOM-API transforms → DOMPurify as
  final boundary (comments/docs updated across ArticleContent,
  sanitize-article-html, AGENTS, ARCHITECTURE).
- **Gate 5**: CJK-aware `estimateReadingTime` (Han 300/min + Latin
  220/min weighted; "< 1 分钟" floor) with ReaderHeader toggle.
- **Gate 6**: `.lumitheme` theme pack (reader-field whitelist export,
  parse→validate→normalize→preview→confirm→apply import, round-trip,
  0010a reader-presets compatibility, missing-font fallback warning).
- **Gate 7**: in-Reader Aa quick panel (desktop popover / mobile bottom
  sheet with focus trap) wired directly to useAppSettings — no second
  store; "更多阅读设置" deep-links to the Settings center.
- **Gate 8**: Shiki code highlight, fine-grained lazy (core + JS-regex
  engine + per-lang/per-theme chunks; 14-language allowlist; unknown →
  plaintext; token colors as classes to comply with the no-inline-style
  sanitize policy).
- **Gate 9**: experimental word-initial emphasis (Latin-only text nodes,
  default off, no speed claims).
- **Gate 10**: paged reading — **deferred** with documented prototype
  conclusion (CSS multi-column selection/column-reflow/table-overflow/
  keyboard/scroll-conflict issues; candidate remains for 0017).
- **Gate 11/12**: Playground reader fixtures (8 scenarios), viewport
  matrix 390–1920 zero overflow (one real bug found & fixed:
  `min-width:0` for code-block min-content), malicious-HTML live
  regression, real-app smoke incl. Aa panel and reading time.

### Verification (final numbers)

```text
Web tests:   399 passed (30 files; 313 baseline + 86 new)
Web lint:    0 errors (3 pre-existing React Compiler notes)
Web build:   success (initial js 451.00KB / gzip 132.66KB, +11.0KB gzip;
             OpenCC/Shiki fully lazy: t2cn 55.06 / cn2t 474.85 / shiki
             core+engine 55.96 gzip, per-lang 0.77–60.65KB)
BFF tests:   134 passed, git diff -- services/bff empty
Live checks: indent/heading scope computed styles; real OpenCC s2t/tw
             conversion + full restore; bionic 12 spans / 0 in code;
             shiki 2 blocks + 154 tokens, plaintext kept; malicious
             fixture renders zero dangerous nodes; 2400px image fits;
             7-viewport zero overflow; real-app Aa panel (popover +
             mobile sheet 44px targets) + "约 2 分钟" reading time;
             console zero errors
```

---

## 10b. Completed work: 0009 — UI Reboot & Reference Lab

All gates user-approved (Gate 0: 2026-08-28; Gates 1–4: 2026-08-29).

### Delivered

- **Gate 0 — audit & v6 docs**: repo/code/test verification; pinned
  read-only references (Folo dev `78f6bd1b`, OrigRead `18d3281`,
  OrigRead-Desktop `8b59bcb4`); license decision AGPL-3.0-only (LICENSE
  added); Folo live audit (measurements in `docs/reference/UPSTREAMS.md`
  §7); v6 documentation baseline (PRD/ARCHITECTURE/AGENTS/README/ROADMAP/
  UI_REBOOT/spec 0009/THIRD_PARTY_NOTICES/docs-reference).
- **Gate 1 — design foundation**: `styles/tokens.css` (radius scale in
  Tailwind @theme, motion 110/140/200ms, z-index, reduced-motion,
  scrollbar) + `styles/themes.css` (Lumi Mist Light/Dark + Reader
  sepia/warm variants); theme logic (`lib/theme.ts` + `store/theme.ts` +
  FOUC-prevention inline script); lucide-react@1.34.0 (ISC, user-approved);
  11 primitives (Button/IconButton/Tooltip/Menu/Popover/Select/Dialog/
  Sheet/Switch/Skeleton/EmptyState + cx); dev-only playground
  (`#/playground`, excluded from production bundle).
- **Gate 2 — shell/Sidebar/Timeline**: grid `240px 400px minmax(0,1fr)`;
  pane layering (sidebar < surface, separator tokens); Sidebar at Folo
  density (32px rows, lucide icons, deterministic category-color dots);
  Timeline two-level rows (unread dot + source/time + title with
  weight-based read state); all Shell components token-migrated.
- **Gate 3 — Reader**: toolbar IconButtons (set semantics, shared
  mutation, pending spinner, aria-pressed preserved); 27px/700 headline;
  46rem content width; 17px/1.75 body typography; Reader theme hook
  (`--lumi-reader-bg` + `data-reader` variants).
- **Gate 4 — polish & regression**: Settings shell (Appearance real:
  theme mode + reader background; Sources/AI/backup explicitly `planned`,
  no fake controls); unified 6px scrollbars; viewport matrix 1920/1440/
  1024/820/390 × light/dark — zero horizontal overflow, zero console
  errors; reversible read/star smoke with zero direct-upstream requests.

### Verification (final numbers)

```text
Web tests:   162 passed (121 pre-0009 + 41 new; zero regression)
Web lint:    0 errors, 2 warnings (React Compiler fast-refresh notes)
Web build:   success (css 30.18KB/gzip 6.91KB, js 290.54KB/gzip 92.03KB)
BFF tests:   121 passed (unchanged; git diff main -- services/bff is empty)
Hard-coded palette classes in src/: zero (AC3 complete)
Viewport matrix: 12 screenshots, all OK (AC16)
Smoke: read/star reversible; console 0 errors; 0 direct upstream requests
```

---

## 11. Test state (final 0012 run, 2026-08-30)

```text
BFF tests:          134 passed  (uv run pytest, zero diff — V1 ✓)
Web tests:          399 passed  (pnpm test, 30 test files)
Web lint:           0 errors, 3 warnings (React Compiler notes)
Web build:          success
Integration checks: see devlog 0012 §12 (visual matrix + real-app
                    smoke via Playwright; malicious-HTML live regression)
Date run:           2026-08-30
Commit tested:      feat/0012-reader-style-deep-customization (worktree)
```

A failure unrelated to 0009 must be reported separately rather than
hidden or "fixed" outside scope.

---

## 12. Exit criteria for 0009

0009 is complete only when:

- the documented architecture and actual code agree;
- the main desktop shell feels cohesive and deliberately designed;
- Sidebar, Timeline and Reader share one token/component system;
- light/dark/system themes work without hard-coded color leaks in
  migrated areas;
- mobile navigation and list/detail flow still work;
- keyboard focus and overlay behavior are usable;
- no existing RSS read/state behavior regresses;
- private reference data is absent from Git;
- upstream/license records are complete for any derived implementation;
- all test/build/visual evidence is reported honestly;
- the user approves the result before commit/push.

---

## 13. After 0009

The next product sequence is intentionally:

```text
UI foundation
  ↓
mobile five-screen alignment                 (0011, active)
  ↓
reader style deep customization              (0012)
  ↓
Lumi-native subscription management           (0013)
  ↓
source discovery and RSSHub route builder     (0014)
  ↓
AI summary                                    (0015)
  ↓
translation and AI conversation               (0016)
  ↓
unified settings / reader power features      (0017)
  ↓
production deployment                         (0018)
  ↓
stabilization and release                     (0019)
```

This order avoids building more product surface on top of a UI
architecture the user already rejects. Global search stays an honest
empty state until the user approves the `0011a Basic Global Search`
contract.

---

## 14. Where things live

- Active spec: `docs/specs/0012-reader-style-deep-customization.md`
- 0011 spec (completed): `docs/specs/0011-mobile-ui-five-screen-alignment.md`
- Mobile reference matrix (0011): `docs/ui/0011-mobile-reference-matrix.md`
- Visual/responsive design direction: `docs/ui/UI_REBOOT.md`
- Roadmap: `docs/ROADMAP.md`
- Upstream baselines and measurements: `docs/reference/UPSTREAMS.md`
- Source map: `docs/reference/SOURCE_MAP.md`
- License audit: `docs/reference/LICENSE_AUDIT.md`
- Progress board (summary view): `docs/progress/index.html`
- Development history: `docs/devlog/`
