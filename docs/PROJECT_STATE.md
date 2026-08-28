# LumiRSS Project State

## Current phase

Phase 2 — BFF (milestones 0002 and 0003 completed; next up 0004 State /
Filter / Pagination)

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
base64url(upstream item id)). The whole path is strictly read-only.

Specs: `docs/specs/0002-bff-freshrss-adapter.md`,
`docs/specs/0003-entry-read-path.md`

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

## Not implemented

- RSSHub
- React Web
- read/star state APIs (writes)
- unread/starred/feed/category filters
- pagination (public cursor/limit contract)
- search
- feed add/delete
- SQLite application persistence
- Runtime AI
- PWA
- Caddy production deployment
- Alibaba ECS deployment

## Next milestone

0004 — State / Filter / Pagination (Phase 2 — BFF continues)

Goal:

```text
read/star state writes
+ unread/starred/feed/category filters
+ pagination
→ on top of the existing read path
```

This completes the Phase 2 backend set.
