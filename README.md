# LumiRSS

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.

It combines mature open-source components (FreshRSS for RSS, RSSHub for
non-RSS sources) with a project-owned FastAPI BFF and a React web client,
plus optional on-demand AI summary and translation.

## Current status

The project is in the **Phase 2 — BFF** stage.

Milestone 0002 is complete: a minimal FastAPI BFF (`services/bff`) with a
FreshRSSAdapter exposes `GET /api/v1/feeds`, which returns the real FreshRSS
subscription list through ClientLogin + subscription/list. No React, no
SQLite, no AI yet. See `docs/specs/0002-bff-freshrss-adapter.md`.

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

BFF development (milestone 0002, requires FreshRSS running):

```bash
cd services/bff
cp .env.example .env      # then fill in your real FreshRSS credentials
uv sync                   # install dependencies (creates uv.lock + .venv)
uv run pytest             # run automated tests (all mocked, no secrets)
uv run uvicorn lumirss.main:app --reload   # start the BFF on http://127.0.0.1:8000
curl http://127.0.0.1:8000/health/live     # → {"status":"ok"}
curl http://127.0.0.1:8000/api/v1/feeds    # → real feeds from FreshRSS
```

Note: `services/bff/.env` holds the real API password and is gitignored;
never commit it.

## Next milestone

Phase 2 continues: Entry Read Path (article list + article detail API).
See `docs/PROJECT_STATE.md`.

## Security

Never commit environment files, credentials, databases, backups or logs.
