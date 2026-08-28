# LumiRSS Project State

## Current phase

Phase 3 — Reading Experience (milestone 0005 Web Shell completed; next up
0006 Reader)

## Current status

PRD v5.0 has been adopted.

Phase 2 — Backend Core (0002–0004) is complete and verified: a FastAPI BFF
under `services/bff` (uv-managed) serves feeds, entry lists, entry detail,
view/feed filters, opaque cursor pagination and set-semantics state writes,
all backed by FreshRSS through the FreshRSSAdapter (tokens stay in process
memory; state stays in FreshRSS).

Milestone 0005 (Web Shell) is complete and verified: the first real LumiRSS
web app lives in `apps/web` (pnpm + React + TypeScript + Vite + Tailwind
CSS v4 + TanStack Query + Zustand). It renders a desktop-first three-pane
shell (sidebar navigation / entry list / reader placeholder), talks only to
relative `/api/v1/*` through the Vite dev proxy (no CORS on the BFF), shows
real feeds and real entries, supports All/Unread/Starred views, feed
filtering (with All Feeds restore), cursor Load More via `useInfiniteQuery`,
and UI-only entry selection. TanStack Query owns all server state; Zustand
owns only view/selectedFeedUrl/selectedEntryRef. 31 automated frontend
tests (Vitest + React Testing Library, mocked fetch); BFF regression 120
passed; real integration smoke (Vite → BFF → FreshRSS) and visual checks
(1440/1280/1024) verified.

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

Specs: `docs/specs/0002-bff-freshrss-adapter.md`,
`docs/specs/0003-entry-read-path.md`,
`docs/specs/0004-entry-state-filter-pagination.md`,
`docs/specs/0005-web-shell.md`

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
  detail/state endpoints intentionally absent — they belong to 0006)
- TanStack Query server-state layer (`useFeeds`, `useEntries` with
  `useInfiniteQuery` + `initialPageParam`/`getNextPageParam` over the
  opaque cursor)
- Zustand UI state (view / selectedFeedUrl / selectedEntryRef only;
  selection cleared on view/feed change; no persist)
- Web Shell UI: three-pane grid (240/400/rest at 100dvh, per-pane
  scrolling), sidebar with views + real feeds + loading/error states,
  entry list with loading/error/empty states, entry rows with
  read/starred/publishedAt display, Load More button, reader placeholder
  fed from the query cache (no detail fetch)
- frontend automated tests (Vitest + jsdom + React Testing Library +
  jest-dom, all mocked fetch; 31 tests)
- real integration verified: Vite dev proxy → BFF → FreshRSS with real
  feeds/entries in the browser; visual checks at 1440/1280/1024

## Not implemented

- RSSHub
- Reader detail / reading view and state mutation UI in the web app
  (entry detail API and PATCH exist on the BFF; the web UI intentionally
  does not use them yet — 0006 Reader)
- Category management and category filtering (deferred — PRD still lists
  it for the reading experience; belongs to a later milestone, it was
  planned for 0004 in an earlier PROJECT_STATE draft but explicitly
  excluded from the 0004 scope)
- Feed add/delete
- SQLite application persistence
- Search
- Mark all as read / batch state writes (single-entry operations only)
- Runtime AI
- PWA and mobile-specific layout
- Caddy production deployment
- Alibaba ECS deployment

## Next milestone

0006 — Reader (Phase 3 — Reading Experience continues)

Goal:

```text
Real reading: entry detail (contentText),
read/star interactions, reader UX
on top of the 0005 Web Shell
```

The 0005 Web Shell provides navigation, lists, pagination and selection;
0006 turns the right pane into a real reader and wires the existing
`GET /api/v1/entries/{entryRef}` and `PATCH /api/v1/entries/{entryRef}/state`
endpoints into the UI.
