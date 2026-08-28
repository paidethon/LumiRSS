# LumiRSS

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.

It combines mature open-source components (FreshRSS for RSS, RSSHub for
non-RSS sources) with a project-owned FastAPI BFF and a React web client,
plus optional on-demand AI summary and translation.

## Current status

The project is in **Phase 3 — Reading Experience**.

Milestone 0005 (Web Shell) is complete: a React + TypeScript + Vite web app
lives in `apps/web` (pnpm-managed). It renders a desktop-first three-pane
shell — sidebar navigation (All / Unread / Starred / real feeds), entry
list (real entries with read/starred indicators), and a reader placeholder
— wired to the BFF through relative `/api/v1/*` requests and the Vite dev
proxy (no CORS on the BFF). TanStack Query owns all server state
(`useInfiniteQuery` + Load More over the opaque cursor); Zustand owns only
the UI selection state (view / feed / entry). No reader detail, no state
mutation UI yet — that is 0006. See `docs/specs/0005-web-shell.md`.

Phase 2 — Backend Core (0002–0004) is complete: feeds, entry list, entry
detail, view/feed filters, opaque cursor pagination and set-semantics
state writes are all available on the BFF. See
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

Web development (milestone 0005, requires the BFF running on :8000):

```bash
cd apps/web
pnpm install              # install dependencies (creates pnpm-lock.yaml)
pnpm dev                  # start Vite dev server on http://localhost:5173
                          # (/api/* is proxied to the BFF on :8000)
pnpm test                 # run Vitest suites (no real network, mocked fetch)
pnpm lint                 # oxlint
pnpm build                # production build (tsc -b + vite build → dist/)
```

Prerequisites: Node.js (LTS, nvm-managed is fine) and pnpm. The web app
needs no environment variables — it only ever talks to relative
`/api/v1/*` paths.

## Next milestone

0006 — Reader: real article reading (entry detail, read/star interactions)
on top of the Web Shell. See `docs/PROJECT_STATE.md`.

## Security

Never commit environment files, credentials, databases, backups or logs.
