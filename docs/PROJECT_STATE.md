# LumiRSS Project State

## Current phase

Phase 3 — Reading Experience **completed** (0005 Web Shell, 0006 Reader
and 0007 Mobile + PWA all done); next up 0008 — RSSHub (Phase 4 —
Source Expansion)

## Current status

PRD v5.0 has been adopted.

Phase 2 — Backend Core (0002–0004) is complete and verified: a FastAPI BFF
under `services/bff` (uv-managed) serves feeds, entry lists, entry detail,
view/feed filters, opaque cursor pagination and set-semantics state writes,
all backed by FreshRSS through the FreshRSSAdapter (tokens stay in process
memory; state stays in FreshRSS).

Milestone 0002 (BFF + FreshRSSAdapter) is complete and verified: a minimal
FastAPI BFF runs under `services/bff` (uv-managed), and `GET /api/v1/feeds`
returns the real FreshRSS subscription list through FreshRSSAdapter
(ClientLogin → auth token in process memory → subscription/list →
normalization to `{title, feedUrl}`).

Milestone 0003 (Entry Read Path) is complete and verified: the BFF can now
read articles. `GET /api/v1/entries` returns the newest entries (bounded
n=20, list fields only — bodies are deliberately dropped) from FreshRSS
`stream/contents/reading-list`, and `GET /api/v1/entries/{entryRef}`
returns one article through `POST stream/items/contents` (single `i`), with
the HTML body converted to safe plain text (`contentText`). Entries are
referenced by an opaque, URL-safe, versioned `entryRef` (`e1.` +
base64url(upstream item id)).

Milestone 0004 (Entry State + Filter + Cursor Pagination) is complete and
verified: entry lists and details now carry `read`/`starred` booleans from
FreshRSS state markers; `GET /api/v1/entries` accepts `view`
(all/unread/starred) and `feedUrl` filters that are translated into
upstream FreshRSS parameters (no post-filtering); pagination uses opaque
`cursor`/`nextCursor` values (`c1.` + base64url JSON envelope carrying the
continuation + filter scope — the raw FreshRSS continuation is never
exposed, mismatched scope is rejected with 400 before touching FreshRSS);
and `PATCH /api/v1/entries/{entryRef}/state` sets (never toggles)
read/starred through Action Token + `edit-tag`, with one-shot 401
recovery. State stays in FreshRSS; tokens stay in process memory.

Milestone 0005 (Web Shell) is complete and verified: a React 19 +
TypeScript + Vite app lives in `apps/web` (pnpm-managed) and renders a
desktop-first three-pane shell — sidebar (All / Unread / Starred + real
feeds), entry list with read/starred indicators and Load More cursor
pagination, and a reader pane — talking to the BFF only through relative
`/api/v1/*` paths via the Vite dev proxy. TanStack Query owns all server
state; Zustand owns only the UI selection state (view / feed / entry).

Milestone 0006 (Reader) is complete and verified: the reader pane is a
real article reader. Selecting an entry triggers a TanStack Query detail
query (`["entry", entryRef]`, enabled only when something is selected,
AbortSignal cancellation on selection change). The BFF's entry detail now
also returns `contentHtml` — the raw upstream FreshRSS HTML, explicitly
documented as UNTRUSTED (the BFF only transports it; the entry list never
gains any body fields). The web client sanitizes it with DOMPurify
(HTML-only profile; form/input/button/textarea/select/option/iframe/
object/embed/style/template forbidden; inline style removed) inside the
single sanctioned `dangerouslySetInnerHTML` boundary (`ArticleContent`),
with `contentText` as plain-text fallback and an explicit empty-body
state. Reader states cover no-selection / loading / success / 404 /
error. The「打开原文」link only renders for absolute http/https URLs
(`safeExternalHttpUrl`). Reading never marks anything read: explicit
read/unread and star/unstar buttons send set-semantics PATCH requests
through one shared `useMutation` (no AbortController on writes); on
success the mutation invalidates `["entry", variables.entryRef]` + the
`["entries"]` prefix so the UI reflects FreshRSS's real state — no
optimistic update. All of this was verified live against real FreshRSS
articles (including reversible read/star smokes with full state
restoration).

Milestone 0007 (Mobile + PWA) is complete and verified: the same React
app is now responsive. Below 1024px the shell switches (CSS media
queries only, no JS width detection) to a Mobile Header + single main
pane + navigation drawer holding the very same `<Sidebar />`; the
mobile list↔reader switch is driven by the existing `selectedEntryRef`
state (null → Entry List, set → full-screen Reader; back =
`selectEntry(null)`, TanStack Query cache is reused, no reload). The
only new UI state is `mobileSidebarOpen` in the existing Zustand store.
Touch targets are ≥44px on mobile, the viewport gained
`viewport-fit=cover` with four `--safe-*` CSS variables, entry-row
titles wrap on phones and the reader uses tighter mobile padding. PWA
installability metadata is in place: a hand-written static
`manifest.webmanifest` (standalone, start_url `/`), locally generated
192/512/maskable-512/apple-touch icons and theme-color — deliberately
**without any Service Worker, offline cache or new dependency**
(installability ≠ offline). All real-browser smokes ran against live
FreshRSS data (856px mobile viewport: drawer open/close/navigation,
entry→reader→back, read/star reversible with full state restoration,
zero horizontal overflow on a 31-image article).

Specs: `docs/specs/0002-bff-freshrss-adapter.md`,
`docs/specs/0003-entry-read-path.md`,
`docs/specs/0004-entry-state-filter-pagination.md`,
`docs/specs/0005-web-shell.md`, `docs/specs/0006-reader.md`

A static web view of this state (project progress board) is available at
`docs/progress/index.html`; development history lives in `docs/devlog/`.

## Implemented

- Git repository
- PRD v5.0
- minimal repository guardrails
- FreshRSS development environment (Docker Compose, single service,
  FreshRSS 1.29.1, bound to 127.0.0.1:8080, data in named volume)
- FreshRSS API access enabled and verified (Google Reader API:
  ClientLogin authentication + subscription/list)
- FastAPI BFF skeleton (`services/bff`, uv-managed, src layout)
- FreshRSSAdapter ClientLogin (async httpx, token in process memory only,
  one-shot re-login on 401)
- FreshRSS subscription read (`subscription/list` normalized to the
  minimal LumiRSS feed model: title + feedUrl)
- GET /api/v1/feeds (real feeds from FreshRSS) and GET /health/live
- automated adapter/route tests (all mocked; health, ClientLogin parsing,
  subscription mapping, config/secret, route wiring, error mapping)
- Entry list read path: GET /api/v1/entries (reading-list, n=20,
  read + unread, bodies dropped)
- Entry detail read path: GET /api/v1/entries/{entryRef}
  (stream/items/contents, single `i`, HTML → contentText)
- entryRef (opaque URL-safe `e1.` + base64url, round-trip, invalid refs
  rejected with 400 before touching FreshRSS)
- text-only entry content (stdlib HTMLParser; no contentHtml exposed)
- entry read automated tests (43 new; 58 total, all mocked)
- Entry read/unread state + starred state (`read`/`starred` on list and
  detail, from FreshRSS state markers)
- Entry view filters (all/unread/starred, translated to upstream `it=`)
- Feed filter (`feedUrl` → feed-scoped stream, URL-encoded upstream path;
  composable with view filters, no post-filtering)
- Cursor pagination (opaque `c1.` cursor envelope with continuation + view
  + feedUrl scope; validation and scope-mismatch → 400 without touching
  FreshRSS)
- Action Token write path (`GET /token` cached in memory, suspicious
  values rejected, never the `T=x`/`T=""` compatibility shortcut)
- PATCH /api/v1/entries/{entryRef}/state (set semantics, strict bool
  validation, 204, one edit-tag request even for combined changes,
  one-shot 401 recovery clearing both tokens)
- entry state/filter/pagination automated tests (62 new; 120 total, all
  mocked)
- React + TypeScript + Vite web app (`apps/web`, pnpm-managed,
  create-vite react-ts template, demo cleaned)
- Tailwind CSS v4 via the official `@tailwindcss/vite` plugin (no legacy
  postcss/tailwind.config.js)
- BFF API client (fetch only; relative `/api/v1` base; ApiError with safe
  messages; cancellation rethrown as-is, never wrapped as network errors;
  0006 added getEntry + setEntryState — 204 responses are not JSON-parsed)
- TanStack Query server-state layer (`useFeeds`, `useEntries` with
  `useInfiniteQuery` + `initialPageParam`/`getNextPageParam` over the
  opaque cursor; 0006 added `useEntryDetail` + `useEntryStateMutation`)
- Zustand UI state (view / selectedFeedUrl / selectedEntryRef only;
  selection cleared on view/feed change; no persist)
- Web Shell UI: three-pane grid (240/400/rest at 100dvh, per-pane
  scrolling), sidebar with views + real feeds + loading/error states,
  entry list with loading/error/empty states, entry rows with
  read/starred/publishedAt display, Load More button (the 0005 reader
  placeholder is now only the no-selection state of the 0006 Reader)
- frontend automated tests (Vitest + jsdom + React Testing Library +
  jest-dom, all mocked fetch; 31 tests)
- real integration verified: Vite dev proxy → BFF → FreshRSS with real
  feeds/entries in the browser; visual checks at 1440/1280/1024
- Entry Detail Reader with per-selection TanStack Query detail fetching
  (`["entry", entryRef]`, enabled only when something is selected)
- Safe RSS HTML rendering: DOMPurify sanitization boundary
  (`sanitize-article-html`, HTML-only profile + FORBID_TAGS/ATTR) +
  `contentText` plain-text fallback + explicit empty-body state
- BFF EntryDetail `contentHtml` (raw untrusted upstream HTML, detail only;
  entry list never gains body fields)
- Original article link (absolute http/https only via
  `safeExternalHttpUrl`, target=_blank + rel=noopener noreferrer)
- Read/unread UI and star/unstar UI (explicit set-semantics writes,
  no auto mark-read, shared mutation, no AbortController on writes)
- TanStack mutation synchronization (invalidate `["entry",
  variables.entryRef]` + `["entries"]` prefix, no optimistic update)
- Reader states: no-selection / loading / success / 404 / error
- reader automated tests (0006; 97 frontend tests total, 121 backend
  tests total, all mocked)
- Responsive mobile layout (<1024px: Mobile Header + single main pane;
  ≥1024px: unchanged three-pane desktop shell; CSS-first, same
  component tree)
- Mobile navigation drawer (same `<Sidebar />` component, explicit
  `onNavigate` close callback, backdrop/✕/Escape close, non-modal
  `<aside>` landmark without aria-modal)
- Mobile Reader flow driven by existing `selectedEntryRef` (no second
  page state; back reuses TanStack Query cache, no reload)
- Touch-friendly controls (≥44px mobile touch targets), phone entry-row
  title wrapping, compact metadata
- Safe-area support (viewport-fit=cover + `--safe-top/right/bottom/left`
  CSS variables used in Mobile Header / drawer / list footer / reader)
- PWA manifest (static `manifest.webmanifest`, standalone display)
- PWA icons (192/512 PNG + 512 maskable + 180 apple-touch-icon, all
  repo-local, generated with a pure Node stdlib PNG encoder)
- Standalone installability metadata (manifest link / theme-color /
  apple-touch-icon in index.html; manifest + icons verified HTTP 200
  with correct content types on the dev server)
- mobile + PWA automated tests (0007; 121 frontend tests total, all
  mocked)

## Not implemented

- Offline support / Service Worker / push notifications (deliberately
  out of scope for the MVP: PWA installability is provided without any
  Service Worker; no offline reading is claimed anywhere)
- RSSHub
- Category management and category filtering (deferred — PRD still lists
  it for the reading experience; belongs to a later milestone, it was
  planned for 0004 in an earlier PROJECT_STATE draft but explicitly
  excluded from the 0004 scope)
- Feed add/delete
- SQLite application persistence
- Search
- Mark all as read / batch state writes (single-entry operations only)
- Runtime AI
- Caddy production deployment
- Alibaba ECS deployment

## Next milestone

0008 — RSSHub (Phase 4 — Source Expansion begins)

Goal:

```text
Non-RSS website → RSSHub → FreshRSS → LumiRSS
```

The reading experience core is complete end to end: the web client
can browse, read (safely rendered), and manage real article state
through the BFF against FreshRSS — on desktop and mobile, installable
as a PWA.
