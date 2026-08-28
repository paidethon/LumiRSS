# LumiRSS

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.

It combines mature open-source components (FreshRSS for RSS, RSSHub for
non-RSS sources) with a project-owned FastAPI BFF and a React web client,
plus optional on-demand AI summary and translation.

## Current status

The project is in **Phase 5 — AI Enhancement** (next up 0009). Phase 4 —
Source Expansion is complete: milestone 0008 added a minimal RSSHub
service to the development Compose environment and proved a real
non-RSS → RSSHub → FreshRSS → LumiRSS path (IT之家热榜 via
`/ithome/ranking/24h`), including failure isolation — with RSSHub
stopped, already-fetched entries remain fully readable through the BFF
and Web. See `docs/specs/0008-rsshub-source-expansion.md`.

Milestone 0006 (Reader) is complete: the right pane of the web shell is a
real reader. Clicking an entry fetches `GET /api/v1/entries/{entryRef}`
through a TanStack Query detail query (`["entry", entryRef]`, only
enabled when something is selected) and renders title / feed / author /
time, a safe "open original" link (only absolute http/https URLs pass
`safeExternalHttpUrl`), and the article body. The BFF now also returns
`contentHtml` (raw upstream HTML — explicitly untrusted; the BFF only
transports it). Before rendering, the web client sanitizes it with
DOMPurify (HTML-only profile + forbidden interactive/embed/style tags) in
the single sanctioned `dangerouslySetInnerHTML` boundary
(`ArticleContent`), with `contentText` as the plain-text fallback. Reading
an article never marks it read: explicit「标记为已读 / 标记为未读」and
「收藏 / 取消收藏」buttons send set-semantics PATCH requests through
`useMutation`; on success the detail query and all entry list queries are
invalidated so the UI shows FreshRSS's real state (no optimistic update).
See `docs/specs/0006-reader.md`.

Milestone 0007 (Mobile + PWA) is complete: the same web app is
responsive. At ≥1024px the three-pane desktop shell is unchanged;
below 1024px it becomes a Mobile Header + single main pane — a
navigation drawer (opened from ☰) holds the very same sidebar, and the
list↔reader switch reuses the existing entry selection state (back =
list, no reload). Touch targets are ≥44px on phones, the viewport uses
`viewport-fit=cover` with safe-area insets, and entry titles wrap
instead of truncating. Basic PWA installability is provided by a static
`manifest.webmanifest` (standalone display) plus locally generated
192/512/maskable/apple-touch icons — deliberately **without** any
Service Worker or offline cache: installing LumiRSS does not make it
usable offline. To install, use the browser's native "Install app" /
"Add to Home Screen" action (development works on localhost, which is
a secure context). See `docs/specs/0007-mobile-pwa.md`.

Milestone 0005 (Web Shell) is complete: a React + TypeScript + Vite web app
lives in `apps/web` (pnpm-managed). It renders a desktop-first three-pane
shell — sidebar navigation (All / Unread / Starred / real feeds), entry
list (real entries with read/starred indicators), and the reader pane —
wired to the BFF through relative `/api/v1/*` requests and the Vite dev
proxy (no CORS on the BFF). TanStack Query owns all server state;
Zustand owns only the UI selection state (view / feed / entry). See
`docs/specs/0005-web-shell.md`.

Phase 2 — Backend Core (0002–0004) is complete: feeds, entry list, entry
detail (plain text + raw HTML), view/feed filters, opaque cursor
pagination and set-semantics state writes are all available on the BFF.
See `docs/specs/0004-entry-state-filter-pagination.md`.

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

RSSHub development (milestone 0008) — converts websites without RSS
feeds into standard feeds, upstream of FreshRSS:

```bash
docker compose up -d rsshub   # start RSSHub on http://127.0.0.1:1200
curl http://127.0.0.1:1200/healthz   # → ok
```

Two different views of the same service:

- The **host** (browser, curl) reaches it at `http://127.0.0.1:1200`
  (loopback binding only — for debugging/probing routes);
- The **FreshRSS container** must subscribe using the Docker service
  DNS name: `http://rsshub:1200/<route>`. Inside the FreshRSS container,
  `localhost` means FreshRSS itself, not RSSHub — so never use
  `127.0.0.1:1200` as a subscription URL.

Verified example: `http://rsshub:1200/ithome/ranking/24h` (IT之家 24h
hot articles, scraped from the website's HTML ranking page). This is a
**basic** RSSHub setup: no Redis, no Browserless, no Chromium — routes
requiring a browser or secrets are not supported.

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
curl http://127.0.0.1:8000/api/v1/entries/<entryRef>   # → one article (contentText + untrusted contentHtml)
# set state (set semantics, not toggle):
curl -X PATCH http://127.0.0.1:8000/api/v1/entries/<entryRef>/state \
  -H 'Content-Type: application/json' -d '{"read": true}'
curl -X PATCH http://127.0.0.1:8000/api/v1/entries/<entryRef>/state \
  -H 'Content-Type: application/json' -d '{"starred": true}'
```

Note: `services/bff/.env` holds the real API password and is gitignored;
never commit it.

Web development (milestones 0005–0006, requires the BFF running on :8000):

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

0009 — AI Summary (Phase 5): on-demand single-article summaries through
an OpenAI-compatible API, cached in SQLite; AI failure must never block
reading. See `docs/PROJECT_STATE.md`.

## Security

Never commit environment files, credentials, databases, backups or logs.
