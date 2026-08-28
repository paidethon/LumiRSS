# LumiRSS

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.

It combines mature open-source components (FreshRSS for RSS, RSSHub for
non-RSS sources) with a project-owned FastAPI BFF and a React web client,
plus optional on-demand AI summary and translation.

## Current status

The project has completed **Phase 2 — Backend Core**.

Milestone 0004 is complete: the BFF now supports entry state, filters and
cursor pagination — `GET /api/v1/entries?view=all|unread|starred&feedUrl=<url>`
(filtered upstream by FreshRSS), opaque cursor pagination
(`cursor`/`nextCursor`, the raw FreshRSS continuation is never exposed),
entry `read`/`starred` fields from FreshRSS, and
`PATCH /api/v1/entries/{entryRef}/state` (set semantics, not toggle) via
Action Token + `edit-tag`. Everything state-related stays in FreshRSS; the
BFF keeps tokens in process memory only. See
`docs/specs/0004-entry-state-filter-pagination.md`.

## Architecture (frozen)

```text
Native RSS ──────────────┐
                         ↓
Non-RSS → RSSHub → FreshRSS
                         ↓
                  FreshRSSAdapter
                         ↓
                    FastAPI BFF
                   ↙           ↘
             FreshRSS         SQLite
                           AI / Cache / Settings
                   ↘           ↙
                    React Web
                         ↓
                Responsive + PWA
                         ↓
                      Caddy
                         ↓
                 Docker Compose
                         ↓
                  Alibaba ECS
```

Explanation of each part: `docs/ARCHITECTURE.md`.

## Documentation

| File | Purpose |
| --- | --- |
| `docs/PRD.md` | Product requirements, v5.0 Reboot Baseline (highest product authority) |
| `docs/ARCHITECTURE.md` | What each component is and why it exists |
| `docs/PROJECT_STATE.md` | Where the project is right now |
| `docs/progress/index.html` | Project progress board (static web view of project state) |
| `AGENTS.md` | Project map for coding agents |

## Development commands

FreshRSS development environment (milestone 0001):

```bash
docker compose up -d   # start FreshRSS on http://localhost:8080
docker compose down     # stop (add -v to also delete data)
```

First-time setup (browser): complete the FreshRSS install wizard, log
in, enable "Allow API access" (Configuration → Authentication), and set
an API password (user menu → Account). See
`docs/specs/0001-freshrss-development-environment.md`.

BFF development (milestones 0002–0004, requires FreshRSS running):

```bash
cd services/bff
cp .env.example .env      # then fill in your real FreshRSS credentials
uv sync                   # install dependencies (creates uv.lock + .venv)
uv run pytest             # run automated tests (all mocked, no secrets)
uv run uvicorn lumirss.main:app --reload   # start the BFF on http://127.0.0.1:8000
curl http://127.0.0.1:8000/health/live     # → {"status":"ok"}
curl http://127.0.0.1:8000/api/v1/feeds    # → real feeds from FreshRSS
curl http://127.0.0.1:8000/api/v1/entries  # → newest entries (no bodies)
# filters (applied upstream by FreshRSS):
curl "http://127.0.0.1:8000/api/v1/entries?view=unread"
curl "http://127.0.0.1:8000/api/v1/entries?view=starred"
curl "http://127.0.0.1:8000/api/v1/entries?feedUrl=<feed-url>"
curl "http://127.0.0.1:8000/api/v1/entries?view=unread&feedUrl=<feed-url>"
# pagination (opaque cursor; a cursor can be replayed on its own):
curl "http://127.0.0.1:8000/api/v1/entries?cursor=<nextCursor>"
# one article:
curl http://127.0.0.1:8000/api/v1/entries/<entryRef>   # → one article as plain text
# set state (set semantics, not toggle):
curl -X PATCH http://127.0.0.1:8000/api/v1/entries/<entryRef>/state \
  -H 'Content-Type: application/json' -d '{"read": true}'
curl -X PATCH http://127.0.0.1:8000/api/v1/entries/<entryRef>/state \
  -H 'Content-Type: application/json' -d '{"starred": true}'
```

Note: `services/bff/.env` holds the real API password and is gitignored;
never commit it.

## Next milestone

Phase 3 — Reading Experience starts with 0005 Web Shell (React app shell
+ layout wired to the BFF /api). See `docs/PROJECT_STATE.md`.

## Security

Never commit environment files, credentials, databases, backups or logs.
