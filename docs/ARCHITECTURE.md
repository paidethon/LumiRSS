# LumiRSS Architecture

This document explains how LumiRSS works as a system. It is written so a
software development beginner can understand it.

Product scope is defined in `docs/PRD.md` (v5.0). This document explains
the frozen architecture: what each part is, why it exists, and how data
flows between the parts.

## The big picture

```text
Content sources
│
├── Native RSS (websites that already publish RSS/Atom feeds)
│
└── Non-RSS websites
      ↓
    RSSHub
      ↓
   FreshRSS
      ↓
FreshRSSAdapter
      ↓
FastAPI BFF
   ↙       ↘
FreshRSS   SQLite
            ↓
       AI / Cache / Settings
   ↘       ↙
 React Web
      ↓
Responsive / PWA
      ↓
    Caddy
      ↓
Docker Compose
      ↓
Alibaba ECS
```

## Why each part exists

### RSSHub

Many websites do not publish standard RSS feeds. RSSHub converts those
websites into standard feeds, so they can be read like normal RSS.

Why it exists: LumiRSS does not build its own crawlers. If a website has
no RSS, RSSHub generates one.

Boundary: RSSHub is an upstream of FreshRSS. It is NOT a second data
backend of LumiRSS, and the BFF never talks to RSSHub directly.

### FreshRSS

FreshRSS is a mature open-source RSS reader backend. It owns all RSS data:

- feeds;
- categories;
- entries (articles);
- read state;
- starred state;
- RSS fetching and updates;
- OPML import/export.

Why it exists: RSS fetching and storage is a solved problem. LumiRSS does
not reinvent it.

Boundary: FreshRSS is the ONLY source of truth for RSS data. LumiRSS never
keeps a second copy of the RSS database.

### FreshRSSAdapter

The adapter translates FreshRSS API responses into LumiRSS domain models.

Why it exists: the rest of LumiRSS must not depend on FreshRSS response
shapes. If the FreshRSS API changes, only the adapter needs to change.

### FastAPI BFF

The BFF ("Backend For Frontend") is the project-owned backend. It is the
only API the web client talks to. It:

- serves the LumiRSS API to the web client;
- calls FreshRSS through the FreshRSSAdapter;
- calls the runtime AI provider when the user asks for it;
- stores LumiRSS-owned data in SQLite.

Why it exists: the web client must never hold credentials, and must never
talk to FreshRSS, RSSHub or the AI provider directly. All secrets stay on
the server.

Boundary: the BFF never re-implements RSS fetching. FreshRSS fetches; the
BFF only reads and passes data along.

### SQLite

SQLite stores ONLY LumiRSS-owned derived data:

- AI summaries;
- AI translations;
- derived caches;
- LumiRSS settings.

Why it exists: AI results and LumiRSS settings belong to LumiRSS, not to
FreshRSS, so they need their own small storage.

Boundary: SQLite is NOT a second RSS database. Full FreshRSS entry data
must never be copied into it.

### React Web

The user interface. Desktop uses a multi-pane reading layout; mobile uses
a list → detail → back flow. Both use the same responsive codebase.

Why it exists: LumiRSS's real value is the reading experience.

Boundary: the web client talks ONLY to the LumiRSS BFF. It never connects
directly to FreshRSS, RSSHub or the runtime AI provider.

### AI provider (optional)

On-demand summary and translation through an OpenAI-compatible API,
triggered only by the user.

Why it exists: it is a convenience enhancement, not the core product.

Boundary: AI is optional. When AI is disabled or failing, LumiRSS must
still be a fully working RSS reader.

### Caddy

The production entry point: HTTPS, static web assets and the `/api`
reverse proxy.

Why it exists: one public origin for both the web client and the API keeps
deployment simple and internal services hidden.

### Docker Compose

Runs all LumiRSS services on one machine with a single configuration.

Why it exists: the final deployment target is a single ordinary Linux VPS
(Alibaba ECS), not a cluster.

## Key data flows

### Reading a normal RSS article

```text
Website → RSS → FreshRSS → BFF → Web
```

### Reading a non-RSS website through RSSHub

```text
Website → RSSHub → FreshRSS → BFF → Web
```

### Marking an article as read

```text
Web → BFF → FreshRSS
```

### On-demand AI summary or translation

```text
Web → BFF → AI provider → SQLite cache → Web
```

## Hard boundaries (do not break)

- FreshRSS is the only RSS source of truth.
- The BFF never fetches or stores RSS content itself.
- SQLite never becomes a second RSS database.
- The web client only talks to the BFF.
- AI failure never blocks reading.
- RSSHub is only an upstream feed generator for FreshRSS, never a
  LumiRSS backend.

## Not designed yet

API fields, database tables, pagination details, authentication schemes,
ORM choices and similar implementation details are intentionally NOT
defined here. They will be decided in the spec of each real feature.
