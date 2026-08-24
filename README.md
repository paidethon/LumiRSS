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
| `AGENTS.md` | Project map for coding agents |

## Development commands

Setup, run, test and Docker commands: **Not implemented yet.**

## Next milestone

FreshRSS development environment. See `docs/PROJECT_STATE.md`.

## Security

Never commit environment files, credentials, databases, backups or logs.
