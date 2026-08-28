# LumiRSS

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.

It combines mature open-source components (FreshRSS for RSS, RSSHub for
non-RSS sources) with a project-owned FastAPI BFF and a React web client,
plus optional on-demand AI summary and translation.

## Current status

The project is in the **Phase 2 — BFF** stage.

Milestone 0003 is complete: the BFF now exposes the entry read path —
`GET /api/v1/entries` (newest entries, bounded n=20, no bodies) and
`GET /api/v1/entries/{entryRef}` (one article as plain text) — reading
through the FreshRSS Google Reader API (`stream/contents/reading-list` /
`stream/items/contents`). Everything is read-only. See
`docs/specs/0003-entry-read-path.md`.

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

BFF development (milestones 0002/0003, requires FreshRSS running):

```bash
cd services/bff
cp .env.example .env      # then fill in your real FreshRSS credentials
uv sync                   # install dependencies (creates uv.lock + .venv)
uv run pytest             # run automated tests (all mocked, no secrets)
uv run uvicorn lumirss.main:app --reload   # start the BFF on http://127.0.0.1:8000
curl http://127.0.0.1:8000/health/live     # → {"status":"ok"}
curl http://127.0.0.1:8000/api/v1/feeds    # → real feeds from FreshRSS
curl http://127.0.0.1:8000/api/v1/entries  # → newest entries (no bodies)
# pick an entryRef from the list above, then:
curl http://127.0.0.1:8000/api/v1/entries/<entryRef>   # → one article as plain text
```

Note: `services/bff/.env` holds the real API password and is gitignored;
never commit it.

## Next milestone

Phase 2 continues: State / Filter / Pagination (read/star state writes,
filters, pagination). See `docs/PROJECT_STATE.md`.

## Security

Never commit environment files, credentials, databases, backups or logs.
