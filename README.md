# LumiRSS

LumiRSS is an invite-based multi-account, self-hosted, source-first
information reader: the operator invites members from an admin console,
each invited member activates their own account, and every account's
subscriptions, reading state, library, AI settings and FreshRSS binding
are fully isolated. Public registration exists as an **optional,
default-off instance policy** (see
[architecture → accounts](https://doc.oouo.top/architecture#accounts)).

Its foundation:

- **FreshRSS** as the RSS-domain engine and source of truth;
- **RSSHub** as an upstream generator for non-RSS sources;
- a project-owned **FastAPI BFF**;
- a responsive **React Web / PWA** client.

Official documentation: **https://doc.oouo.top/**

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
[doc.oouo.top/architecture](https://doc.oouo.top/architecture).

---

## Quick start (development)

```bash
git clone https://github.com/paidethon/LumiRSS.git && cd LumiRSS
docker compose up -d          # FreshRSS + RSSHub
cd services/bff && cp .env.example .env && uv sync && uv run uvicorn lumirss.main:app --reload
cd ../../apps/web && pnpm install && pnpm dev
```

Full guide: [doc.oouo.top/getting-started](https://doc.oouo.top/getting-started).

---

## Production deployment

```bash
sudo ./lumirss deploy                      # interactive
sudo ./lumirss deploy --auth-mode=session  # persistent session login (primary mode; basic-auth stays as a compat option)
sudo ./lumirss deploy --low-memory         # low-resource preset for small self-hosts
sudo ./lumirss deploy --single             # optional single-container topology (Caddy + BFF + FreshRSS + RSSHub in one container)
```

Caddy serves the Web build and reverse-proxies `/api` to the BFF;
FreshRSS / RSSHub stay on the internal network. Automated TLS, health
endpoints, backups (local + WebDAV) and staged restore are included.
Full runbook: [doc.oouo.top/operations](https://doc.oouo.top/operations).

---

## Documentation

The documentation site is built from the same `docs/` Markdown that
GitHub renders — one source, two renderers.

| You want… | Read |
|---|---|
| Run it locally / self-host quick start | [getting-started](https://doc.oouo.top/getting-started) |
| Daily usage (reading / sources / AI / data control) | [usage](https://doc.oouo.top/usage) |
| Deploy / upgrade / roll back / back up / troubleshoot | [operations](https://doc.oouo.top/operations) |
| Configuration keys | [configuration](https://doc.oouo.top/configuration) |
| Architecture & invariants | [architecture](https://doc.oouo.top/architecture) |
| Design system | [design-system](https://doc.oouo.top/design-system) |
| Contributing / tests / CI | [development](https://doc.oouo.top/development) |
| What comes next | [roadmap](https://doc.oouo.top/roadmap) |

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
