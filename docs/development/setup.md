# Development Setup

## Prerequisites

- Docker & Docker Compose (for FreshRSS + RSSHub)
- Python 3.12+ with `uv` (for BFF)
- Node.js 20+ with `pnpm` (for Web)

## FreshRSS and RSSHub

```bash
docker compose up -d
```

Use exact Compose versions from the local repository. Never place real
credentials in Git.

## BFF (FastAPI)

```bash
cd services/bff
cp .env.example .env    # edit with local FreshRSS credentials
uv sync
uv run pytest           # verify setup
uv run uvicorn lumirss.main:app --reload
```

BFF runs locally and connects to FreshRSS via the configured URL.

## Web (React)

```bash
cd apps/web
pnpm install
pnpm dev                # start dev server
pnpm test               # run tests
pnpm lint               # check lint
pnpm build              # production build
```

The Web client uses relative `/api/v1/*` requests and must not receive
FreshRSS/RSSHub/AI secrets.

## Progress Dashboard

```bash
# Open directly in browser (zero dependencies, vanilla HTML/CSS/JS)
open tools/progress-dashboard/index.html
```

The dashboard reads from `project-data.js` and is NOT the source of truth.
Project state comes from `docs/README.md` and `docs/ROADMAP.md`.

## Reference Repositories

Reference projects for UI research are cloned as read-only siblings:

```text
../LumiRSS-reference/Folo
../LumiRSS-reference/OrigRead
../LumiRSS-reference/OrigRead-Desktop
```

Never edit, push, vendor or submodule them into LumiRSS.
