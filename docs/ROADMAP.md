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
0009–0010
    ↓
Mobile UI five-screen alignment
0011
    ↓
Reader style deep customization
0012
    ↓
Lumi-native source control
0013–0014
    ↓
AI reading assistance
0015–0016
    ↓
Reader/settings completion
0017
    ↓
Production and MVP release
0018–0019
    ↓
Knowledge Workbench Phase 2
```

The former `0009 — AI Summary` is renumbered to `0015 — AI Foundation & Summary`（0010/0010a/0011 三次路线修订顺延）。

0010 路线修订（2026-08-29，用户批准）：插入 `0010 — Settings Center & Adaptive Shell`（设置中心 + 自适应外壳，纯前端）；原 0010–0016 顺延为 0011–0017。原因：设置与外壳是所有后续功能的承载面，优先于订阅管理。

0010a 路线修订（2026-08-30，用户批准）：插入 `0011 — Reader Style Deep Customization`（阅读样式深度自定义：字体导入/中文排版/主题包分享，依据 reader-style-survey 调研）；原 0011–0017 顺延为 0012–0018。同时决策：JSON 规则/网站解析规则（自造源）不做——违反冻结架构，同等需求由 RSSHub 承担（0013）；OrigRead 规则页 UI 模式作为 0013 设计蓝本。

0011 路线修订（2026-08-30，用户批准）：尚未开工的原 `0011 — Reader Style Deep Customization`（spec 未写）被替换为 `0011 — Mobile UI Navigation & Five-Screen Alignment`（移动端导航与五页面 UI 对齐，依据用户提供的 Spec0011 Bundle 与五张参考图）；原 0011–0018 顺延为 0012–0019。同时决策：搜索能力不做在 0011 内（诚实空态），立候选里程碑 `0011a Basic Global Search`（待用户单独批准 BFF 契约后再排期）。

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

## 0010 — Settings Center & Adaptive Shell

**Status:** Implemented + 0010a expansion（Gate A–D + E/F/G，2026-08-30）

### Goal

Build the product shell: a Folo-style settings center (declarative setting rows, 9 categories — 5 real today, 4 planned with milestone attribution), sidebar information architecture (信息来源 / 工作区 groups with Phase 2 items visible-but-disabled), draggable/collapsible three panes with persisted widths, and a mobile bottom tab bar — all client-side (localStorage), zero BFF changes.

### Deliverables

- typed app-settings store (single localStorage key + legacy key migration);
- SettingItem declarative renderer + SettingsModal (13-category left nav);
- keyboard shortcuts (j / k / u / s) + cheatsheet page;
- pane separators (pointer drag / arrow keys / double-click reset) with aria semantics;
- sidebar regrouping (信息来源 / 工作区, Phase 2 badges);
- mobile bottom tabs + Folo-style push settings (grouped list → subpages);
- **0010a**: appearance (accent picker / global font size / UI font / reduce motion),
  reader style P0 (font stacks / background palette + custom hex + WCAG adaptive
  text / paragraph spacing / justify / image modes), P1 (custom CSS with scoped
  prefixing, 5 typography presets + derive/import/export), general timeline
  (dim read / group by date / unread-only start / experimental scroll-mark-read),
  OrigRead-inspired pages (translation providers, filter rules + display-layer
  filtering, RSSHub instances, encrypted config backup via Web Crypto);
- progress board content + visual unification (Lumi Mist, dark mode).

### Acceptance

Every interactive control genuinely works and persists; planned items are disabled with milestone labels; 0009 behavior tests stay green; BFF untouched.

---

## 0011 — Mobile UI Navigation & Five-Screen Alignment

**Status:** **Implemented**（spec docs/specs/0011-mobile-ui-five-screen-alignment.md，2026-08-30 用户批准；含后续 fix PR #18 rss-scope/category-tree）

### Goal

对齐移动端 Web 的首页/订阅/搜索/收藏/侧边栏五个界面（用户提供的五张参考图）：
建立 AppSection 一级导航模型与四项底部导航岛（首页/订阅/搜索/收藏）、
设置入口统一到侧边栏品牌区右上角、RSS 源 disclosure 默认收起、
共享 EntryCard 与移动页 Header、订阅/搜索页诚实降级（无契约不造假）、
Playground 五场景 fixture 与七视口截图矩阵。纯前端，BFF 零改动。

### Acceptance

见 active spec AC1–AC13（四 tab 状态转换、设置同位、RSS 折叠语义、
收藏复用 starred 查询、抽屉 modal/focus trap、无横向 overflow、
不伪造数据、既有行为零回归）。

### 候选：0011a — Basic Global Search

仅当用户单独批准搜索 BFF 契约后启动（FreshRSS greader 协议无搜索能力，
需评估其他方案）；在此之前搜索页保持诚实空态。

---

## 0012 — Reader Style Deep Customization

**Status:** **Active spec**（docs/specs/0012-reader-style-deep-customization.md，2026-08-30 用户指令批准；调研依据 docs/reference/reader-style-survey.md）

### Goal

Deep reading-style customization: font import (FontFace + IndexedDB, woff2 only
+ font-URL alternative for CJK sizes), Chinese typography (first-line indent /
punctuation hanging / S2T conversion / CJK reading time), theme pack sharing
(.lumitheme JSON with presets + custom CSS), code highlight themes (shiki,
lazy), Bionic Reading, paged scroll (candidate).

### Acceptance

Fonts persist and load offline; theme packs round-trip import/export; Chinese
typography options verifiable in computed styles; zero BFF changes.

---

## 0013 — Unified Subscription Center

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

## 0014 — Source Discovery & RSSHub Integration

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

## 0015 — AI Foundation & Summary

**Status:** Planned; renumbered from old 0009 (0009→0012→0013→0014→0015)

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

## 0016 — Translation & AI Conversation

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

## 0017 — Reader Power UX & Unified Settings

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

## 0018 — Production & Operations

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

## 0019 — MVP Stabilization & Release

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
0010 Settings Center & Adaptive Shell (+0010a)
 ├─ no backend dependency (localStorage only)
 └─ enables coherent settings/panes for all later features

0011 Mobile UI Navigation & Five-Screen Alignment
 ├─ no backend dependency (AppSection store + responsive shell)
 └─ shared EntryCard/MobilePageHeader feed subscriptions/search/
    favorites surfaces (0013/0011a) and all later mobile UX

0012 Reader Style Deep Customization
 ├─ no backend dependency (FontFace/IndexedDB/local presets)
 └─ builds on 0010a reader-style variable system

0013 Subscription Center
 └─ depends on FreshRSS control capability; activates BFF-layer
    filtering (0010a display-layer rules migrate) + OPML backup

0014 Source Discovery
 ├─ depends on 0013 subscribe flow
 └─ introduces RSSHub catalog/control boundary; activates RSSHub
    instance testing (0010a instance list migrates); OrigRead
    rule-page UI patterns as design reference

0015 AI Summary
 └─ depends on Reader/design/settings foundations

0016 Translation/Chat
 └─ depends on 0015 provider/cache foundation; activates
    translation execution + test-connection + DeepL usage
    (0010a saved provider configs migrate)

0017 Unified Settings
 ├─ consolidates 0009/0010 theme & client settings
 ├─ consolidates 0013/0014 source settings
 ├─ consolidates 0015/0016 AI settings + server-side API
 └─ formalizes experimental scroll-mark-read

0018 Production
 └─ depends on stable service and secret boundaries

0019 Stabilization
 └─ depends on all MVP feature milestones

0011a Basic Global Search (candidate, requires user-approved
search contract; otherwise search stays honest-empty in 0011)
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

