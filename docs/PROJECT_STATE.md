# LumiRSS Project State

## Current phase

Phase 2 — Backend Core (milestones 0002–0004 completed; next up 0005
Web Shell, Phase 3 — Reading Experience)

## Current status

PRD v5.0 has been adopted.

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
`docs/specs/0004-entry-state-filter-pagination.md`

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

## Not implemented

- RSSHub
- React Web
- Category management and category filtering (deferred — PRD still lists
  it for the reading experience; belongs to a later milestone, it was
  planned for 0004 in an earlier PROJECT_STATE draft but explicitly
  excluded from the 0004 scope)
- Feed add/delete
- SQLite application persistence
- Search
- Mark all as read / batch state writes (single-entry operations only)
- Runtime AI
- PWA
- Caddy production deployment
- Alibaba ECS deployment

## Next milestone

0005 — Web Shell (Phase 3 — Reading Experience starts)

Goal:

```text
React app shell + overall layout
navigation / article list / reading area
wired to the BFF /api
```

Phase 2 Backend Core is complete: the BFF now covers feeds, entry list,
entry detail, state writes, filters and cursor pagination — enough to
support the first React reader.
