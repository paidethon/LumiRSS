# LumiRSS

LumiRSS is a single-user, self-hosted, source-first information reader.

Its current foundation combines:

- **FreshRSS** as the RSS-domain engine and source of truth;
- **RSSHub** as an upstream generator for supported non-RSS sources;
- a project-owned **FastAPI BFF**;
- a responsive **React Web / PWA** client;
- optional AI assistance planned after the UI and source workflows are stable.

> Status: v6 baseline adopted 2026-08-28 (verified against the local repository during 0009 Gate 0).

---

## Current status

Milestone **0011 — Mobile UI Navigation & Five-Screen Alignment** is the
active spec (approved 2026-08-30): align the mobile Web home /
subscriptions / search / favorites / sidebar surfaces with the user's
five reference images via an `AppSection` navigation model, a four-tab
floating bottom bar, a shared mobile page header and honest data
degradation (no fabricated backend fields; zero BFF changes). See
`docs/specs/0011-mobile-ui-five-screen-alignment.md` and
`docs/ui/0011-mobile-reference-matrix.md`.

Milestone 0010 + 0010a expansion (Settings Center & Adaptive Shell) is
complete (2026-08-30): a Folo-style settings center (13 categories —
appearance/accent picker, reader typography P0, custom CSS + 5 typography
presets, translation providers, filter rules with display-layer filtering,
RSSHub instances, encrypted config backup via Web Crypto), Folo-style
mobile push settings, adaptive panes, and a Lumi Mist unified progress
board — all client-side (localStorage), **zero BFF changes** (Web 244 /
BFF 121 tests green). See `docs/devlog/0010-settings-center-adaptive-shell.md`.

Milestone 0009 (UI Reboot & Reference Lab) is complete (2026-08-29): the
Lumi Mist design system — semantic tokens with Light/Dark/System themes,
11 shared UI primitives, Folo-density Sidebar/Timeline/Reader, Reader
theme separation. See `docs/devlog/0009-ui-reboot-reference-lab.md`.

Milestones 0001–0008 are complete: RSS reading foundation end to end —
FreshRSS + minimal RSSHub (verified non-RSS ingestion path with failure
isolation), FastAPI BFF (feeds / entries / filters / cursor pagination /
set-semantics state writes), React Web shell + Reader + responsive
mobile flow + basic installable PWA.

See:

- `docs/PROJECT_STATE.md`
- `docs/ROADMAP.md`
- `docs/specs/0011-mobile-ui-five-screen-alignment.md`

---

## Product direction

Normal users should use **LumiRSS as the only daily interface**.

The target experience is:

```text
Add source
  ↓
Lumi discovers direct RSS or an RSSHub route
  ↓
Preview and subscribe in Lumi
  ↓
FreshRSS stores RSS-domain state
  ↓
Read, star, search, summarize and configure in Lumi
```

FreshRSS and RSSHub remain mature internal services. Their original Web pages may remain available as advanced diagnostic escape hatches, but normal workflows should not require switching between multiple products.

Long-term, Lumi may expand into an integrated knowledge workspace containing RSS, web clips, structured APIs, email newsletters, Obsidian-library information and an Agent context layer. These Phase 2 capabilities are not part of the current MVP implementation.

---

## Architecture

### RSS read path

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

Rules:

- FreshRSS owns subscriptions, entries, read state and starred state for the RSS domain;
- RSSHub generates feeds upstream and is not the entry database;
- Web talks only to the Lumi BFF;
- the BFF keeps upstream credentials and maps upstream protocols to Lumi contracts;
- Lumi SQLite is reserved for application settings, AI/cache metadata and future non-RSS connector data, not a duplicate RSS database.

### Planned source control path

```text
React Web
   ↓
FastAPI BFF
   ├─ FreshRSSControlAdapter
   └─ RSSHubCatalog / Control Adapter
```

This future control plane will enable subscribe/unsubscribe/category/OPML, route search, parameter forms, preview, health and selected safe settings inside Lumi without bypassing FreshRSS in the normal read path.

Full explanation: `docs/ARCHITECTURE.md`.

---

## Current API baseline

Verified against local code (2026-08-28):

```text
GET   /health/live
GET   /api/v1/feeds
GET   /api/v1/entries
GET   /api/v1/entries/{entryRef}
PATCH /api/v1/entries/{entryRef}/state
```

Important behavior:

- entry references and cursors are opaque;
- opening an article does not automatically mark it read;
- read/star writes use explicit set semantics;
- article HTML is untrusted and sanitized before rendering;
- server state belongs to TanStack Query; lightweight UI selection belongs to Zustand.

---

## UI direction

The proposed UI reboot uses:

- **Folo** as the primary interaction/layout reference;
- **OrigRead Desktop** as the secondary Settings/source/reader-tools reference;
- a Lumi-owned muted theme named **Lumi Mist / 雾光**;
- pale blue-indigo as the default accent;
- warm-neutral low-saturation surfaces and restrained category colors;
- independent app and Reader themes;
- responsive desktop/tablet/mobile layouts;
- a future floating desktop AI panel and mobile Bottom Sheet built around a shared core.

The goal is:

```text
Folo interaction parity, not Folo product parity.
```

Lumi does not copy Folo's community, reward, recommendation or social product scope.

---

## Repository structure

The exact local tree is authoritative. Public baseline:

```text
LumiRSS/
├── apps/web/              React Web / PWA
├── services/bff/          FastAPI BFF
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── PROJECT_STATE.md
│   ├── ROADMAP.md
│   └── specs/
├── docker-compose.yml     development services
├── AGENTS.md
└── README.md
```

Reference projects for 0009 must be cloned as read-only sibling directories, not committed into LumiRSS.

---

## Development

### FreshRSS and RSSHub

```bash
docker compose up -d
```

Use the exact Compose documentation and pinned versions from the local repository. Do not place real credentials in Git.

### BFF

Likely commands, verify locally:

```bash
cd services/bff
cp .env.example .env
uv sync
uv run pytest
uv run uvicorn lumirss.main:app --reload
```

### Web

Likely commands, verify locally:

```bash
cd apps/web
pnpm install
pnpm dev
pnpm test
pnpm lint
pnpm build
```

The Web client uses relative `/api/v1/*` requests and must not receive FreshRSS/RSSHub/AI secrets.

---

## Documentation

| File | Purpose |
|---|---|
| `docs/PRD.md` | product requirements and scope |
| `docs/ARCHITECTURE.md` | component responsibilities and data/control paths |
| `docs/PROJECT_STATE.md` | factual current state and immediate next work |
| `docs/ROADMAP.md` | milestone order and future phases |
| `docs/ui/UI_REBOOT.md` | detailed visual/responsive design direction |
| `docs/specs/0011-mobile-ui-five-screen-alignment.md` | active milestone spec |
| `docs/ui/0011-mobile-reference-matrix.md` | 0011 reference-image alignment matrix |
| `AGENTS.md` | durable rules for coding agents |
| `docs/reference/*` | pinned upstreams, source map and license gate |

---

## Security

Never commit:

- `.env` or API credentials;
- FreshRSS API passwords;
- RSSHub cookies/tokens;
- AI keys;
- databases/backups/private logs;
- browser profiles/cookies/localStorage;
- logged-in reference screenshots containing private data.

RSS/website HTML is untrusted. Keep sanitization and safe-link checks intact. Future source discovery must include SSRF, redirect, timeout and response-size defenses.

---

## License

LumiRSS is licensed under **AGPL-3.0-only** (see `LICENSE`, adopted by user decision on 2026-08-28). This enables compliant adaptation of AGPL-licensed upstream references while preserving copyright obligations.

Known constraints:

- Folo uses AGPL-3.0 and explicitly restricts redistribution of its `icons/mgc` content (never copy it);
- OrigRead Desktop uses AGPL-3.0-only;
- OrigRead Android uses GPL-3.0;
- source-derived work must be recorded in `docs/reference/SOURCE_MAP.md` and relevant notices;
- restricted upstream icons/assets must not be copied.

See `docs/reference/LICENSE_AUDIT.md`.

---

## Roadmap at a glance

```text
0001–0008  RSS reader foundation                         implemented baseline
0009       UI Reboot & Reference Lab                     completed 2026-08-29
0010       Settings Center & Adaptive Shell (+0010a)     completed 2026-08-30
0011       Mobile UI Navigation & Five-Screen Alignment  active spec
0012       Reader Style Deep Customization               planned
0013       Unified Subscription Center                   planned
0014       Source Discovery & RSSHub Integration         planned
0015       AI Foundation & Summary                       planned
0016       Translation & AI Conversation                 planned
0017       Reader Power UX & Unified Settings            planned
0018       Production & Operations                       planned
0019       MVP Stabilization & Release                   planned
Phase 2    Web/API/Email/Obsidian/Agent Workbench        deferred
```

