# LumiRSS

LumiRSS is a single-user, self-hosted, source-first information reader.

Its current foundation:

- **FreshRSS** as the RSS-domain engine and source of truth;
- **RSSHub** as an upstream generator for non-RSS sources;
- a project-owned **FastAPI BFF**;
- a responsive **React Web / PWA** client.

> LumiRSS is under active MVP development.
> Documentation and project status: [docs/README.md](docs/README.md)

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
client talks only to the Lumi BFF. Full explanation: [docs/architecture/README.md](docs/architecture/README.md).

---

## Development

### FreshRSS and RSSHub

```bash
docker compose up -d
```

### BFF

```bash
cd services/bff
cp .env.example .env
uv sync
uv run pytest
uv run uvicorn lumirss.main:app --reload
```

### Web

```bash
cd apps/web
pnpm install
pnpm dev
pnpm test
pnpm build
```

Detailed development guide: [docs/development/](docs/development/)

---

## API baseline

```text
GET   /health/live
GET   /api/v1/feeds
GET   /api/v1/entries
GET   /api/v1/entries/{entryRef}
PATCH /api/v1/entries/{entryRef}/state
```

Entry references and cursors are opaque. Opening an article does not
auto-mark it read. Read/star writes use set semantics.

---

## License

LumiRSS is licensed under **AGPL-3.0-only** (see `LICENSE`).

Known upstream licenses: Folo AGPL-3.0 (icons/mgc redistribution restricted),
OrigRead Desktop AGPL-3.0-only, OrigRead Android GPL-3.0.

See [docs/upstream/LICENSE_AUDIT.md](docs/upstream/LICENSE_AUDIT.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

## Security

Never commit `.env`, API credentials, FreshRSS/RSSHub secrets, AI keys,
databases or private screenshots. RSS/website HTML is untrusted — keep
sanitization and safe-link checks intact.
