# AGENTS.md — LumiRSS v6 Agent Working Agreement

> 本文件面向 Qoder、Codex、Claude Code、Cursor、OpenCode 等编码代理。
>
> 状态：**Adopted v6 baseline**（已经 0009 Gate 0 本地仓库事实校准，用户于 2026-08-28 批准）。本文不能替代实际仓库事实。

---

## 1. Project identity

LumiRSS is a single-user, self-hosted, source-first information reader.

Current product scope:

- RSS / Atom subscriptions;
- non-RSS sources converted by RSSHub and stored/read through FreshRSS;
- a project-owned FastAPI BFF;
- a responsive React Web / PWA client;
- optional AI summary, translation and conversation in later milestones.

Long-term direction:

- RSS;
- web clipping;
- structured JSON/API sources;
- email newsletters;
- Obsidian-library integration;
- unified search and an Agent-oriented knowledge workspace.

Do not describe Phase 2 features as already implemented.

---

## 2. Authority order

When documents disagree, use this priority:

1. Current executable code and tests;
2. `docs/specs/<active-spec>.md`;
3. `docs/ARCHITECTURE.md`;
4. `docs/PRD.md`;
5. `docs/PROJECT_STATE.md`;
6. `docs/ROADMAP.md`;
7. `README.md`;
8. Historical plans, devlogs and chat transcripts.

Before modifying code, compare the relevant sources. Do not silently choose one side of a conflict. Record the conflict and resolve it explicitly.

---

## 3. Current milestone

当前已批准的里程碑：

```text
0011 — Mobile UI Navigation & Five-Screen Alignment
       （分支 feat/0011-mobile-ui-five-screen-alignment，active spec：
        docs/specs/0011-mobile-ui-five-screen-alignment.md）
```

0009（UI Reboot）与 0010/0010a（Settings Center & Adaptive Shell）
均已合入 main。0011 对齐移动端首页/订阅/搜索/收藏/侧边栏五个
界面：AppSection 一级导航 + 四项底部导航岛（首页/订阅/搜索/收藏）、
设置入口统一到侧边栏品牌区右上角、RSS 源 disclosure 默认收起、
抽屉升级为完整 modal/focus trap。全程纯前端（BFF 零变化）；
数据契约零造假（无搜索/分类/未读数契约时诚实降级）。

路线编号（2026-08-30 三次修订，用户批准）：尚未开工的原 0011
（Reader Style Deep Customization）被替换为 0011（Mobile UI
Navigation & Five-Screen Alignment），原 0011–0018 顺延为 0012–0019；
AI Summary（原 0009）现为 0015。搜索能力不做在 0011 内，立候选
里程碑 0011a Basic Global Search（待用户单独批准 BFF 契约）。
详见 docs/ROADMAP.md 变更记录。

---

## 4. Non-negotiable architecture boundaries

### 4.1 RSS read path

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

- FreshRSS remains the source of truth for the **RSS domain**: feeds, entries, read state and starred state.
- RSSHub is an upstream feed generator, not the RSS database.
- The normal reader data path must not read article state directly from RSSHub.
- The BFF owns translation between upstream protocols and stable Lumi contracts.
- The Web client talks only to relative Lumi BFF endpoints such as `/api/v1/*`.
- Never expose FreshRSS credentials, RSSHub secrets or AI provider secrets to the browser.

### 4.2 Source and service control path

Lumi must become the normal user-facing control surface:

```text
React Web
   ▼
FastAPI BFF
   ├─ FreshRSSControlAdapter
   │    ├─ subscribe / unsubscribe
   │    ├─ rename / move category
   │    ├─ OPML import / export
   │    └─ health / selected user settings
   │
   └─ RSSHubCatalogAdapter / RSSHubControlAdapter
        ├─ route catalog and search
        ├─ route-parameter forms
        ├─ preview and health
        └─ allow-listed instance configuration
```

This control plane is **planned**, not necessarily implemented in the current repository. Do not claim otherwise.

### 4.3 Future unified source layer

FreshRSS is not the source of truth for future web clips, API records, email or Obsidian documents.

Future connectors must sit behind a Lumi-owned unified source layer. Do not force non-RSS content into FreshRSS merely to reuse its database.

### 4.4 SQLite responsibility

Lumi SQLite may store:

- AI cache and job metadata;
- Lumi application settings;
- connector metadata and secrets references;
- source registry records not owned by FreshRSS;
- future cross-source indexes and processing state.

It must not become a shadow copy of the FreshRSS feed and entry database during MVP.

---

## 5. Existing behavior that 0009 must preserve

Verify locally before relying on this list. The public baseline indicates that 0001–0008 already provide:

- FreshRSS development environment;
- a FastAPI BFF with feed, entry list, entry detail and state-write endpoints;
- opaque `entryRef` and opaque pagination cursor;
- explicit set semantics for read/starred state;
- safe article rendering using DOMPurify at a single sanctioned HTML boundary;
- a React three-pane shell;
- responsive list/reader behavior below the desktop breakpoint;
- static PWA manifest and icons without offline cache;
- a minimal RSSHub service and a verified RSSHub → FreshRSS → Lumi path.

During 0009:

- opening an article must still not automatically mark it read;
- read and star changes must keep set semantics rather than toggle semantics;
- cursor opacity must remain intact;
- the browser must not access FreshRSS directly;
- the browser must not access RSSHub directly for normal reading;
- article sanitization must not be weakened;
- no backend data model or API contract may be casually redesigned to make the UI easier.

If UI needs data that the current API does not provide, use a graceful fallback and document the missing contract for a later approved milestone.

---

## 6. UI / UX direction

### 6.1 Reference hierarchy

1. **Folo** — primary reference for desktop shell, sidebar, timeline density, reader hierarchy, light/dark surfaces, selection states, micro-interactions and future AI floating panel.
2. **OrigRead Desktop** — secondary reference for settings, source discovery, reader tools, resizable panes, AI panel/dock and RSSHub-oriented workflows.
3. **OrigRead Android / other readers** — mobile and source-discovery patterns.
4. **User-provided palette image** — color philosophy only, not layout.
5. **Lumi brand** — final identity, theme system and product boundaries.

The goal is:

> Folo interaction parity, not Folo product parity.

Do not copy Folo's community, social, recommendation, reward, creator or commercial features into the MVP.

### 6.2 Default visual language

Default theme name:

```text
Lumi Mist / 雾光
```

Character:

- warm-neutral canvas;
- quiet, low-saturation surfaces;
- pale blue-indigo primary accent;
- muted pastel category colors;
- subtle separators;
- restrained radii;
- shadows only for overlays and true elevation;
- dense but readable timeline;
- content-first reader.

Avoid:

- large gradients;
- glass effects on every surface;
- wrapping every section in cards;
- excessive `rounded-xl` / `rounded-2xl`;
- large saturated purple or blue areas;
- decorative shadows on ordinary list rows;
- dashboard/SaaS aesthetics;
- multiple unrelated icon styles.

### 6.3 Semantic tokens only

All reusable components must consume semantic variables, not hard-coded brand colors.

Required token groups:

```text
canvas / sidebar / surface / elevated / reader
surface-hover / surface-selected / surface-pressed
text-primary / text-secondary / text-tertiary / text-disabled
border / separator / focus-ring
accent / accent-hover / accent-pressed / accent-soft / accent-contrast
success / warning / danger / info
category-blue / green / orange / purple / cyan / rose / red
shadow-popover / shadow-dialog / shadow-floating
radius-xs / sm / md / lg / xl
motion-fast / normal / slow
```

The application theme and reader theme are separate. Future custom accent colors must not require component rewrites.

### 6.4 Component primitives

Before page-level polish, establish or adopt consistent primitives:

- Button;
- IconButton;
- Input;
- Select;
- Menu / MenuItem / MenuSeparator;
- Popover;
- Tooltip;
- Dialog;
- Drawer;
- BottomSheet;
- Switch;
- Tabs / SegmentedControl;
- Badge;
- Skeleton;
- EmptyState;
- ResizablePane / Divider.

Reuse existing dependencies when suitable. New packages require justification, license check and user approval when they materially change the stack.

### 6.5 Icon policy

Use one legal, maintainable icon system. `lucide-react` is a reasonable candidate but must be approved before installation.

Never copy or redistribute Folo's `icons/mgc` directory. Its repository contains an explicit redistribution exception.

### 6.6 Responsive behavior

The same product behavior must adapt by container, not by hiding functionality.

Recommended initial ranges, to be validated with the current layout:

```text
>= 1440px       full three-pane shell; future AI floating overlay
1200–1439px     compact three panes; AI overlay or drawer
1024–1199px     collapsible sidebar; timeline + reader
768–1023px      list/detail navigation; sidebar drawer; AI sheet/drawer
< 768px         single-column mobile web; AI bottom sheet/fullscreen route
```

Do not create a second disconnected mobile application during MVP. Reuse data hooks, state semantics and core content components.

### 6.7 Future AI surface

AI is optional and non-blocking.

The same `AiChatCore` should eventually render as:

- floating panel on large desktop;
- right drawer or dock on smaller desktop/tablet;
- bottom sheet on mobile;
- fullscreen route for long conversations.

Do not implement AI chat in milestone 0009 unless an approved spec says so. 0009 may only prepare the layout shell and component boundary.

---

## 7. Reference repositories

Keep reference projects outside LumiRSS:

```text
../LumiRSS-reference/Folo
../LumiRSS-reference/OrigRead
../LumiRSS-reference/OrigRead-Desktop
```

They are read-only research inputs.

Never:

- edit them;
- run automated fixes against them;
- commit or push to them;
- copy their full dependency trees;
- vendor them into LumiRSS;
- add them as Git submodules without explicit approval.

Pin each reference by branch and commit SHA in `docs/reference/UPSTREAMS.md`.

For every reused idea or code path, update `docs/reference/SOURCE_MAP.md` with one classification:

- `inspired` — visual/behavior idea only;
- `rewritten` — independently implemented after study;
- `adapted` — source-derived implementation with meaningful changes;
- `copied` — substantially copied source.

`adapted` and `copied` entries require license review and attribution before merge.

---

## 8. License gate

The public LumiRSS root did not expose a license at the time this proposal was prepared. Verify locally.

Known reference licenses at proposal time:

- Folo: AGPL-3.0, plus a special exception prohibiting redistribution of `icons/mgc` content;
- OrigRead Desktop: AGPL-3.0-only;
- OrigRead Android: GPL-3.0.

Rules:

- Do not make a license choice on the user's behalf.
- Do not directly adapt/copy source until the project license decision is approved.
- If substantial Folo or OrigRead Desktop code is incorporated, evaluate AGPL-3.0-only as the likely compatible project license.
- Maintain `THIRD_PARTY_NOTICES.md` and per-file attribution where required.
- A visual resemblance alone does not justify copying assets, icons or text.
- This repository's documentation is not legal advice; uncertain cases must be flagged.

---

## 9. Security and privacy

### 9.1 Secrets

Never commit:

- `.env` files;
- API passwords;
- FreshRSS credentials;
- RSSHub cookies/tokens;
- AI keys;
- browser profiles/cookies/localStorage;
- backups, databases or private logs;
- screenshots containing private subscriptions or account data.

Use redacted examples and `.env.example` only.

### 9.2 Browser Agent

When auditing a logged-in Folo account:

- the user performs login manually;
- the agent must not request, copy or expose credentials/session data;
- browsing is read-only;
- no subscription, state, account, AI or settings changes;
- private screenshots stay outside Git in a gitignored folder.

### 9.3 HTML content

RSS/website content is untrusted.

- Preserve the single audited sanitized HTML-rendering boundary.
- Do not add arbitrary iframe/script/style support.
- External links must use safe protocols and appropriate `rel` values.
- Any future full-text extraction output remains untrusted and is sanitized in the client or a clearly documented trusted pipeline.

### 9.4 Service control

Do not mount `/var/run/docker.sock` into the normal Web BFF merely to restart RSSHub or FreshRSS.

Any future service-control adapter must:

- expose an allow-list of operations;
- validate values;
- avoid arbitrary command execution;
- record safe, redacted diagnostics;
- clearly distinguish immediate settings from settings requiring reload/restart.

---

## 10. Backend conventions

Validate actual package structure before editing. Preserve existing conventions.

General expectations:

- explicit typed request/response models;
- stable Lumi-owned DTOs rather than leaking raw FreshRSS shapes;
- adapter-specific errors translated to stable API errors;
- timeouts on all upstream calls;
- bounded retries only for safe/idempotent operations;
- no secret values in logs or exception text;
- deterministic set semantics for state writes;
- pagination cursors remain opaque;
- tests mock upstream network unless an explicit integration suite is being run;
- health endpoints distinguish liveness from dependency readiness where appropriate.

Planned adapters must be separate by responsibility:

```text
FreshRSSAdapter          # read/list/detail/state data plane
FreshRSSControlAdapter   # subscription/settings/OPML control plane
RSSHubCatalogAdapter     # route metadata/search/form schema
RSSHubControlAdapter     # health/preview/allow-listed configuration
AIProviderAdapter        # optional AI provider boundary
```

Do not create a single god-service that combines all external systems.

---

## 11. Frontend conventions

Validate actual project setup first.

General expectations:

- TypeScript strictness is preserved;
- TanStack Query owns server state;
- Zustand owns only lightweight client UI state;
- avoid duplicating server records into global client stores;
- centralize query keys;
- reusable primitives live separately from domain components;
- no direct fetch to FreshRSS/RSSHub/provider endpoints from the browser;
- all network states need loading, empty and error UI;
- keyboard and focus behavior are part of acceptance, not later polish;
- avoid arbitrary pixel values when a token exists;
- do not put business logic inside visual primitives;
- do not silently add a heavy UI framework.

Recommended UI organization, adapted to actual repository conventions:

```text
apps/web/src/
├── components/ui/
├── features/navigation/
├── features/timeline/
├── features/reader/
├── features/settings/
├── features/sources/
├── features/ai/
├── styles/tokens.css
├── styles/themes.css
├── styles/reader.css
└── styles/motion.css
```

This is a direction, not a mandatory mass move. Avoid churn for its own sake.

---

## 12. Accessibility requirements

New UI must meet at least these requirements:

- visible keyboard focus;
- logical tab order;
- icon-only controls have accessible labels;
- hover is never the only way to discover critical actions;
- no information encoded by color alone;
- text/background contrast is checked in light and dark themes;
- mobile targets are at least approximately 44×44 CSS pixels for primary actions;
- drawers/dialogs/sheets trap and restore focus correctly;
- `Escape` closes dismissible desktop overlays;
- reduced-motion preference disables nonessential motion;
- semantic headings and landmarks are preserved in the reader.

---

## 13. Testing and validation

Before claiming completion, rerun the commands available in the current repository. Likely categories include:

### BFF

```bash
cd services/bff
uv sync
uv run pytest
```

### Web

```bash
cd apps/web
pnpm install
pnpm test
pnpm lint
pnpm build
```

Do not assume these exact commands if the local repository differs.

For 0009 add visual/responsive checks at:

```text
1920 × 1080
1440 × 900
1024 × 768
820 × 1180
390 × 844
```

Required states:

- loading;
- empty feeds;
- empty entries;
- selected entry;
- unread/read;
- starred/unstarred;
- network/API error;
- very long title/source name;
- article without image;
- article without HTML;
- light/dark/system themes;
- keyboard navigation;
- mobile drawer and list→reader back flow.

Screenshots are evidence, not a substitute for behavioral tests.

---

## 14. Git and change discipline

At task start:

```bash
git branch --show-current
git status --short --branch
git log --oneline --decorate -12
git rev-parse HEAD
```

Rules:

- stop if there are unexpected user changes;
- never `reset --hard`, `clean -fd`, force push or overwrite user work;
- do not create commits without explicit approval;
- keep changes scoped to the active spec;
- do not mix documentation baseline, dependency changes and page redesign in one unreviewable commit;
- proposed commit sequence for 0009:
  1. docs/reference baseline;
  2. design tokens and primitives;
  3. app shell;
  4. sidebar;
  5. timeline;
  6. reader;
  7. settings shell and responsive polish;
  8. tests/docs.

Commit messages should be descriptive and avoid claiming unverified outcomes.

---

## 15. Documentation maintenance

When a milestone changes behavior, update together:

- active spec;
- `docs/PROJECT_STATE.md`;
- `docs/ROADMAP.md`;
- `README.md` if public status changes;
- `docs/ARCHITECTURE.md` if a responsibility or data path changes;
- `docs/PRD.md` only for product-scope/decision changes;
- `AGENTS.md` for durable agent rules;
- source/license records for upstream-derived work.

Do not put transient debugging notes in durable architecture documents.

Use explicit labels:

- `Implemented`;
- `Partially implemented`;
- `Planned`;
- `Deferred`;
- `Rejected`.

Never write future functionality in present tense.

---

## 16. Definition of done for an agent task

A task is done only when:

1. scope matches the approved spec;
2. existing behavior is preserved or intentionally migrated;
3. tests and builds were rerun and outputs reported honestly;
4. responsive and keyboard states were inspected;
5. no secrets/private screenshots entered Git;
6. source/license records were updated where relevant;
7. documentation reflects actual implementation;
8. remaining gaps and risks are listed;
9. no commit/push/PR was made without user approval.

---

## 17. Stop conditions

Stop and ask for approval when:

- the working tree contains unknown changes;
- a required source file or dependency differs materially from this proposal;
- API changes appear necessary during 0009;
- source reuse would trigger an unresolved license choice;
- adding a heavy dependency is proposed;
- a reference repository would need modification;
- browser audit would require changing private user data;
- a service operation would require Docker socket or arbitrary shell access;
- tests fail for reasons unrelated to the current task;
- completing the task would expand into Phase 2 features.

