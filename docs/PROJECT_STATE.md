# LumiRSS Project State

## Current phase

Phase 2 — BFF (milestone 0002 completed; next up 0003 Entry Read Path)

## Current status

PRD v5.0 has been adopted.

Milestone 0002 (BFF + FreshRSSAdapter) is complete and verified: a minimal
FastAPI BFF runs under `services/bff` (uv-managed), and `GET /api/v1/feeds`
returns the real FreshRSS subscription list through FreshRSSAdapter
(ClientLogin → auth token in process memory → subscription/list →
normalization to `{title, feedUrl}`).

Spec: `docs/specs/0002-bff-freshrss-adapter.md`

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

## Not implemented

- RSSHub
- React Web
- Entry (article) API
- read/star state APIs
- SQLite application persistence
- Runtime AI
- PWA
- Caddy production deployment
- Alibaba ECS deployment

## Next milestone

0003 — Entry Read Path (Phase 2 — BFF continues)

Goal:

```text
FreshRSS
→ FreshRSSAdapter
→ FastAPI
→ article list + article detail API
```

Together with 0002 this completes the minimal Phase 2 backend set.
