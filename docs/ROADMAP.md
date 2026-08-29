# LumiRSS Roadmap v6

> 状态：Adopted（用户于 2026-08-28 批准）
>
> 路线原则：先稳定产品骨架与用户入口，再增加来源、AI 和知识工作台能力。每个里程碑都必须形成一个可验证闭环，不允许一次性横跨多个阶段。

---

## 1. Roadmap summary

```text
Completed foundation
0001–0008
    ↓
UI and product shell
0009
    ↓
Lumi-native source control
0010–0011
    ↓
AI reading assistance
0012–0013
    ↓
Reader/settings completion
0014
    ↓
Production and MVP release
0015–0016
    ↓
Knowledge Workbench Phase 2
```

The former `0009 — AI Summary` is renumbered to `0012 — AI Foundation & Summary`.

---

## 2. Status legend

| Status | Meaning |
|---|---|
| Implemented | behavior exists and has evidence in code/tests/docs |
| Partially implemented | useful subset exists; remaining scope is explicit |
| Planned | approved direction but not implemented |
| Proposed | requires user approval before becoming the active spec |
| Deferred | intentionally after MVP |
| Rejected | explicitly outside product direction |

---

## 3. Completed milestones

### 0001 — FreshRSS Development Environment

**Status:** Implemented, verify locally.

Outcome:

- reproducible FreshRSS development service;
- documented first-time setup and API credentials;
- persistent local data boundary;
- secret files excluded from Git.

### 0002 — BFF Foundation

**Status:** Implemented, verify locally.

Outcome:

- FastAPI package and health route;
- FreshRSS adapter/authentication boundary;
- typed configuration and tests;
- browser no longer needs FreshRSS credentials.

### 0003 — Feed and Entry Read APIs

**Status:** Implemented, verify locally.

Outcome:

- feeds endpoint;
- entry list/detail foundation;
- stable Lumi-owned response mapping.

### 0004 — Entry State, Filters and Pagination

**Status:** Implemented, verify locally.

Outcome:

- all/unread/starred/feed views;
- opaque cursor pagination;
- explicit read/starred writes;
- upstream state remains authoritative.

### 0005 — Web Shell

**Status:** Implemented, visually temporary.

Outcome:

- React/TypeScript/Vite Web app;
- TanStack Query server state;
- Zustand UI selection state;
- functional three-pane shell.

### 0006 — Reader

**Status:** Implemented, visually temporary.

Outcome:

- real detail query;
- sanitized HTML rendering;
- safe original link;
- explicit read/star controls;
- opening an entry does not auto-mark read.

### 0007 — Responsive Web and Basic PWA

**Status:** Implemented, requires 0009 regression protection.

Outcome:

- mobile header/drawer;
- list→reader flow;
- safe-area and touch-target handling;
- Manifest and icons;
- no offline claim.

### 0008 — RSSHub Source Expansion

**Status:** Implemented, minimal profile.

Outcome:

- official RSSHub image pinned by digest;
- non-RSS source converted upstream of FreshRSS;
- route verified through Lumi;
- failure isolation proven for previously fetched entries;
- no Redis/browser automation/advanced secrets.

---

## 4. Proposed MVP milestones

## 0009 — UI Reboot & Reference Lab

**Status:** Proposed next

### Goal

Replace the temporary visual shell with a coherent, responsive Lumi design system while preserving all 0001–0008 behavior.

### Primary references

- Folo: shell, Sidebar, Timeline, Reader, micro-interactions, themes;
- OrigRead Desktop: Settings, reader tools, source workflows, panes;
- user palette: muted warm-neutral surfaces and pastel categories;
- Lumi: pale blue-indigo accent and its own identity.

### Deliverables

- pinned, read-only reference repositories;
- browser/UI measurement audit;
- license/source maps;
- semantic tokens and Lumi Mist light/dark themes;
- shared UI primitives;
- refined responsive App Shell;
- Sidebar, Timeline and Reader redesign;
- Settings shell;
- future AI overlay boundary;
- responsive/keyboard/accessibility regression evidence.

### Non-goals

- AI implementation;
- subscription APIs;
- RSSHub route builder;
- backend redesign;
- Folo social/recommendation features;
- offline Service Worker;
- native mobile app.

### Gate

Documentation/audit must be approved before code.

---

## 0010 — Unified Subscription Center

**Status:** Planned

### Goal

Allow normal subscription management entirely inside Lumi.

### Deliverables

- add direct RSS/Atom URL;
- preview source metadata before subscribing;
- subscribe/unsubscribe;
- rename/move category;
- OPML import/export;
- health/error states;
- safe confirmation for destructive operations;
- FreshRSS Web UI retained only as an advanced escape hatch.

### Architecture

Introduce a narrowly scoped `FreshRSSControlAdapter` rather than adding subscription mutations to visual components or leaking FreshRSS APIs to the browser.

### Acceptance

A user can add, categorize and remove a normal RSS feed from Lumi without opening FreshRSS.

---

## 0011 — Source Discovery & RSSHub Integration

**Status:** Planned

### Goal

Turn “paste a website” into a guided source-discovery workflow.

### Deliverables

- URL normalization and validation;
- direct RSS/Atom detection;
- HTML-declared feed/common endpoint detection;
- RSSHub route catalog ingestion and versioning;
- route search and website matching;
- dynamic parameter form generation;
- indication of required instance configuration;
- route preview through the BFF;
- one-click subscription into FreshRSS;
- RSSHub health/settings surface;
- SSRF, redirects, timeout and output-limit controls.

### Non-goals

- arbitrary website scraping rules;
- generic browser automation;
- complete JSON/API connector;
- exposing Docker socket.

### Acceptance

A supported non-RSS website can be discovered, configured, previewed and subscribed from Lumi without reading RSSHub documentation or manually composing a route URL.

---

## 0012 — AI Foundation & Summary

**Status:** Planned; renumbered from old 0009

### Goal

Provide optional, on-demand article summaries without making AI part of the reading critical path.

### Deliverables

- one OpenAI-compatible provider boundary initially;
- server-side secret storage;
- model and language settings;
- prompt versioning;
- cache key including entry/content/provider/model/prompt/language dimensions;
- pending/success/error states;
- retry with bounded behavior;
- provider/model/time metadata;
- inline Reader summary card;
- no automatic paid requests without explicit product decision.

### Acceptance

AI can fail completely and normal reading/state/source workflows still work.

---

## 0013 — Translation & AI Conversation

**Status:** Planned

### Goal

Add translation and context-aware article conversation on top of the AI foundation.

### Deliverables

- title/full-article translation;
- translation cache and language settings;
- article-scoped AI conversation;
- shared `AiChatCore`;
- large desktop floating panel;
- desktop drawer/dock mode;
- mobile Bottom Sheet;
- fullscreen conversation route;
- conversation history and context controls within explicit privacy limits.

### Non-goals

- autonomous Agent actions;
- hidden background ingestion of private sources;
- multi-agent orchestration.

---

## 0014 — Reader Power UX & Unified Settings

**Status:** Planned

### Goal

Complete the normal daily product experience before production hardening.

### Deliverables

- app mode: system/light/dark;
- palette preset and custom accent;
- independent reader background;
- font/size/line-height/max-width controls;
- compact/comfortable timeline density if justified;
- keyboard shortcuts;
- pane sizing persistence;
- search/filter polish;
- unified Settings categories;
- selected FreshRSS/RSSHub diagnostics and settings;
- clear advanced escape hatches.

### Acceptance

A normal user can configure Lumi, Reader, FreshRSS-backed sources, RSSHub and AI from one coherent Settings experience.

---

## 0015 — Production & Operations

**Status:** Planned

### Goal

Deploy safely and maintainably on the target server.

### Deliverables

- production Compose/profile;
- Caddy same-origin routing and TLS;
- single-user access strategy;
- persistent volumes;
- health/readiness;
- redacted structured logs;
- backup/restore procedures;
- upgrade/rollback notes;
- resource limits suitable for target ECS;
- RSSHub advanced dependencies only when a real route needs them;
- diagnostics without broad container privileges.

### Acceptance

A fresh server can deploy, back up, restore, upgrade and roll back using documented procedures.

---

## 0016 — MVP Stabilization & Release

**Status:** Planned

### Goal

Freeze scope, remove critical defects and publish a trustworthy MVP.

### Deliverables

- full regression suite;
- accessibility review;
- responsive matrix;
- security review for untrusted content/source discovery/secrets;
- performance budgets;
- empty/loading/error coverage;
- license and third-party notice review;
- final README and operator guide;
- recovery drill;
- versioned release notes.

### MVP exit criteria

- normal subscription workflow stays inside Lumi;
- RSSHub-supported source workflow stays inside Lumi;
- reading, read/star state, responsive Reader and themes are stable;
- AI remains optional;
- deployment/backup/restore are documented and tested;
- no unresolved high-severity security/license issue.

---

## 5. Phase 2 — Integrated Knowledge Workbench

Phase 2 begins only after MVP stabilization.

### 2A — Web Clipping / Read Later

- browser share/clip endpoint;
- capture provenance and original URL;
- clean-text extraction;
- highlights/notes/tags;
- duplicate handling;
- content update policy;
- read-later collection separate from FreshRSS RSS truth.

Reference patterns may be studied from projects such as Readeck, but implementation must fit Lumi's connector model.

### 2B — Structured JSON/API Sources

- connector schemas;
- authenticated and public APIs;
- schedule/rate limits;
- field mapping and stable IDs;
- per-connector tests;
- safe secrets and retries.

### 2C — Email Newsletters

- dedicated inbound address or mailbox connector;
- MIME/HTML sanitization;
- sender/source identity;
- thread/duplicate rules;
- attachment policy;
- privacy controls.

### 2D — Obsidian Library Connector

- read-only first;
- explicit vault/folder allow-list;
- frontmatter and link indexing;
- update detection;
- no destructive vault writes by default;
- later write-back only with granular confirmation.

### 2E — Unified Source Registry and Search

- common identity/provenance model;
- connector-native references;
- full-text/metadata search;
- filters by source/type/time/tags;
- retention and re-index behavior.

### 2F — Agent Workspace

- retrieval through the unified source layer;
- explicit tool permissions;
- citations/provenance in answers;
- user-confirmed write actions;
- resumable task history;
- no direct unrestricted access to service credentials or filesystem.

---

## 6. Explicitly rejected or deferred directions

### Rejected for MVP

- Folo product clone;
- community/social graph;
- creator economy/reward system;
- algorithmic recommendation feed;
- multi-user/OAuth platform;
- arbitrary Docker administration from the Web BFF;
- copying Folo icon assets with redistribution restrictions;
- duplicating FreshRSS's complete RSS database into Lumi SQLite;
- native iOS/Android app before responsive Web is stable.

### Deferred until real need

- Redis/Celery;
- vector database;
- generic semantic search;
- browser automation service;
- multi-provider model routing;
- automatic AI processing of every article;
- offline-first Web/PWA;
- n8n orchestration.

---

## 7. Dependency map

```text
0009 UI Reboot
 ├─ no backend dependency
 └─ enables coherent later surfaces

0010 Subscription Center
 └─ depends on FreshRSS control capability

0011 Source Discovery
 ├─ depends on 0010 subscribe flow
 └─ introduces RSSHub catalog/control boundary

0012 AI Summary
 └─ depends on Reader/design/settings foundations

0013 Translation/Chat
 └─ depends on 0012 provider/cache foundation

0014 Unified Settings
 ├─ consolidates 0009 theme settings
 ├─ consolidates 0010/0011 source settings
 └─ consolidates 0012/0013 AI settings

0015 Production
 └─ depends on stable service and secret boundaries

0016 Stabilization
 └─ depends on all MVP feature milestones
```

---

## 8. Progress reporting format

At the end of each milestone update:

```text
Milestone:
Branch / commit:
Implemented:
Not implemented:
API changes:
Data migration:
Tests run and exact results:
Screenshots / manual checks:
Security/license notes:
Known gaps:
Next milestone:
```

Do not report percentage complete without an explicit denominator. Prefer a checklist of verified outcomes.

---

## 9. Time-boxing for a limited evening schedule

The user has limited development time. Each subtask should fit one reviewable session where possible:

```text
Session A: audit / plan
Session B: one primitive or one data contract
Session C: one visual/domain component
Session D: tests and review
```

Large agent runs must stop at review gates rather than modifying the entire roadmap in one pass.

---

## 10. Roadmap change policy

A roadmap change requires updating:

- `docs/ROADMAP.md`;
- `docs/PROJECT_STATE.md`;
- affected spec numbers and cross-links;
- README current/next milestone;
- PRD if product scope or a durable decision changes;
- AGENTS if agent rules change.

Never renumber or delete completed specs without preserving traceability.

