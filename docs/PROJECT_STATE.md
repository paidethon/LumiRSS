# LumiRSS Project State

> v6.0 — verified against the local repository; 0009 implementation
> completed 2026-08-29 (Gates 0–4, all user-approved).

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

Completed next milestone:

```text
0009 — UI Reboot & Reference Lab   (completed 2026-08-29)
0010 — Unified Subscription Center (next)
```

AI Summary (renumbered from old 0009) stays at milestone 0012.

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
| 0010 Unified Subscription Center | **Next** | add/manage subscriptions inside Lumi | After 0009 |
| 0011 Source Discovery & RSSHub | Planned | URL/RSSHub discovery, route forms and preview | After 0010 |
| 0012 AI Foundation & Summary | Planned | on-demand summary, cache and safe status | Replaces old 0009 |
| 0013 Translation & AI Conversation | Planned | translation and responsive AI chat surfaces | After 0012 |
| 0014 Reader Power UX & Unified Settings | Planned | reading preferences, settings, power navigation | Later MVP |
| 0015 Production & Operations | Planned | Caddy, deployment, backup, diagnostics | Later MVP |
| 0016 MVP Stabilization | Planned | regression, docs, accessibility and release | MVP exit |

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

- subscription control API (0010);
- OPML API (0010);
- RSSHub route catalog/preview API (0011);
- unified settings API (0014);
- AI provider/cache/jobs (0012–0013);
- deployment authentication (0015);
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
  planned (0015).

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

## 10. Completed work: 0009 — UI Reboot & Reference Lab

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

## 11. Test state (final 0009 run, 2026-08-29)

```text
BFF tests:          121 passed  (uv run pytest, unchanged code)
Web tests:          162 passed  (pnpm test, 13 test files)
Web lint:           0 errors, 2 warnings (oxlint; React Compiler notes)
Web build:          success (js 290.54KB / gzip 92.03KB)
Integration checks: reversible read/star smoke via real FreshRSS data;
                    console 0 errors; 0 direct upstream requests
Visual viewport checks: 12 screenshots (5 sizes × 2 themes + settings
                    dialog + mobile reader), zero horizontal overflow
Date run:           2026-08-29
Commit tested:      feat/0009-ui-reboot-reference-lab (worktree)
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
Lumi-native subscription management        (0010)
  ↓
source discovery and RSSHub route builder  (0011)
  ↓
AI summary                                 (0012)
  ↓
translation and AI conversation            (0013)
  ↓
unified settings / reader power features   (0014)
  ↓
production deployment and stabilization    (0015–0016)
```

This order avoids building more product surface on top of a UI
architecture the user already rejects.

---

## 14. Where things live

- Active spec: `docs/specs/0009-ui-reboot-reference-lab.md`
- Visual/responsive design direction: `docs/ui/UI_REBOOT.md`
- Roadmap: `docs/ROADMAP.md`
- Upstream baselines and measurements: `docs/reference/UPSTREAMS.md`
- Source map: `docs/reference/SOURCE_MAP.md`
- License audit: `docs/reference/LICENSE_AUDIT.md`
- Progress board (summary view): `docs/progress/index.html`
- Development history: `docs/devlog/`
