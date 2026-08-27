# LumiRSS Project State

## Current phase

Phase 2 — BFF (next up; Phase 1 milestone 0001 completed)

## Current status

PRD v5.0 has been adopted.

Milestone 0001 (FreshRSS development environment) is complete and
verified: FreshRSS 1.29.1 runs via Docker Compose on localhost:8080,
and the Google Reader API (ClientLogin + subscription/list) works
against a real subscription.

Spec: `docs/specs/0001-freshrss-development-environment.md`

A static web view of this state (project progress board) is available at
`docs/progress/index.html`; development history lives in `docs/devlog/`.

No LumiRSS runtime application service is implemented yet.

## Implemented

- Git repository
- PRD v5.0
- minimal repository guardrails
- FreshRSS development environment (Docker Compose, single service,
  FreshRSS 1.29.1, bound to 127.0.0.1:8080, data in named volume)
- FreshRSS API access enabled and verified (Google Reader API:
  ClientLogin authentication + subscription/list)

## Not implemented

- RSSHub
- FreshRSSAdapter
- FastAPI BFF
- React Web
- SQLite application persistence
- Runtime AI
- PWA
- Caddy production deployment
- Alibaba ECS deployment

## Next milestone

Phase 2 — BFF (FastAPI + FreshRSSAdapter)

Goal:

```text
FreshRSS
→ FreshRSSAdapter
→ FastAPI
→ /api
```

At least feeds, article list and article detail.

## Do not start yet

- React
- AI
- production deployment
- Folo
- multi-backend
- advanced infrastructure
