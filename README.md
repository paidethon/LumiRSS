# LumiRSS

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.

It combines mature open-source components (FreshRSS for RSS, RSSHub for
non-RSS sources) with a project-owned FastAPI BFF and a React web client,
plus optional on-demand AI summary and translation.

## Current status

The project is in the **Reboot / Foundation** stage.

Application services are not implemented yet. This repository currently
contains only product and architecture documentation plus minimal
repository guardrails. There is no runnable application code.

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

Other commands: **Not implemented yet.**

## Next milestone

Phase 2 — BFF (FastAPI + FreshRSSAdapter). See `docs/PROJECT_STATE.md`.

## Security

Never commit environment files, credentials, databases, backups or logs.
