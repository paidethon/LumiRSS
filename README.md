# LumiRSS

LumiRSS is an invite-based multi-account, self-hosted, source-first
information reader: the operator invites members from an admin console,
each invited member activates their own account, and every account's
subscriptions, reading state, library, AI settings and FreshRSS binding
are fully isolated. There is no public registration.

Its foundation:

- **FreshRSS** as the RSS-domain engine and source of truth;
- **RSSHub** as an upstream generator for non-RSS sources;
- a project-owned **FastAPI BFF**;
- a responsive **React Web / PWA** client.

On top of that foundation it ships: article reading with explicit
read/star state, subscriptions & categories with OPML import/export,
AI summary / translation / article conversation, the Lumi library
(bookmarks / server-side web clips / offline snapshots), workspaces &
server-side read-later, inbox push sources, API sources & newsletter
bridges feeding FreshRSS, a read-only Obsidian vault projection,
unified search with tags / favorites / graph, an optional RAG-indexed
semantic layer plus an Agent workbench, a unified settings center, and
local + WebDAV backup with staged restore. See
[docs/ROADMAP.md](docs/ROADMAP.md) for exact feature status.

---

## Architecture

```text
Native RSS / Atom ───────────────┐
                                  ▼
Non-RSS source → RSSHub → FreshRSS
                                  ▼
                         FreshRSSAdapter
                                  ▼
                           FastAPI BFF
                                  ▼
                              React Web
```

FreshRSS owns RSS-domain state. RSSHub generates feeds upstream. The Web
client talks only to the Lumi BFF. Full explanation:
[docs/explanation/architecture.md](docs/explanation/architecture.md).

---

## Quick start (development)

```bash
git clone https://github.com/paidethon/LumiRSS.git && cd LumiRSS
docker compose up -d          # FreshRSS + RSSHub
cd services/bff && cp .env.example .env && uv sync && uv run uvicorn lumirss.main:app --reload
cd ../web && pnpm install && pnpm dev
```

Full guide: [docs/getting-started.md](docs/getting-started.md).

---

## Production deployment

```bash
sudo ./lumirss deploy                      # interactive
sudo ./lumirss deploy --auth-mode=session  # persistent session login
sudo ./lumirss deploy --low-memory         # low-resource preset for small self-hosts
```

Caddy serves the Web build and reverse-proxies `/api` to the BFF;
FreshRSS / RSSHub stay on the internal network. Automated TLS, health
endpoints, backups (local + WebDAV) and staged restore are included.
Full runbook: [docs/how-to/deploy.md](docs/how-to/deploy.md).

---

## Documentation

| You want… | Read |
|---|---|
| Run it locally | [docs/getting-started.md](docs/getting-started.md) |
| Deploy / upgrade / roll back | [docs/how-to/deploy.md](docs/how-to/deploy.md) |
| Invite members (admin) | [docs/how-to/invite-members.md](docs/how-to/invite-members.md) |
| Back up / restore | [docs/how-to/backup-restore.md](docs/how-to/backup-restore.md) |
| Troubleshoot | [docs/how-to/troubleshoot.md](docs/how-to/troubleshoot.md) |
| Configuration keys | [docs/reference/configuration.md](docs/reference/configuration.md) |
| Architecture & invariants | [docs/explanation/architecture.md](docs/explanation/architecture.md) |
| Docs index | [docs/README.md](docs/README.md) |

---

## License

LumiRSS is licensed under **AGPL-3.0-only** (see `LICENSE`). Upstream
license notes: [docs/upstream/LICENSE_AUDIT.md](docs/upstream/LICENSE_AUDIT.md)
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Security

Never commit `.env`, API credentials, FreshRSS/RSSHub secrets, AI keys,
databases or private screenshots. RSS/website HTML is untrusted — keep
sanitization and safe-link checks intact (see
[AGENTS.md](AGENTS.md)).
