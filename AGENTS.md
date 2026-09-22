# AGENTS.md — LumiRSS Agent Working Agreement

> For Qoder, Codex, Claude Code, Cursor, OpenCode and similar coding agents.
> This file contains durable rules, not project encyclopedia.
> Verify against actual repository state before relying on it.

---

## 1. Project identity

LumiRSS is an invite-based multi-account, self-hosted, source-first
information reader: RSS/Atom via FreshRSS, non-RSS via RSSHub, a FastAPI
BFF, and a responsive React Web / PWA client. The operator invites
members from the admin console; each invitee activates their own account
(one-time, expiring invite → self-chosen username/password at
`/activate`), and every account's subscriptions, reading state, library,
AI settings and FreshRSS binding are fully isolated (control DB + per-user
DBs, server-derived identity — see docs/decisions/
0005-invite-multi-account.md). There is no public registration.

Feature status lives in one place: [docs/ROADMAP.md](docs/ROADMAP.md)
(implemented / next / deferred). Do not copy feature inventories into
agent prompts or docs — link instead.

NOT implemented — do not describe these as existing: web clipping browser
extension, Obsidian write-back (the vault stays read-only), MCP surface,
PWA push / background sync, public registration / multi-tenant tenancy.
LumiRSS is small-scale invite-only by design (the operator's own
deployment, members they personally invited); public-internet hardening
and multi-tenancy guarantees remain out of scope. All data-protection
rules below (secrets never to the browser, DOMPurify boundary, no Docker
socket, per-account isolation) still apply exactly as written.

---

## 2. Architecture invariants

These are non-negotiable. Full explanation: [docs/explanation/architecture.md](docs/explanation/architecture.md).

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

- FreshRSS owns RSS-domain state (feeds, entries, read/star);
- RSSHub is an upstream generator, not the entry database;
- Web client talks only to Lumi BFF (`/api/v1/*`);
- Upstream credentials and secrets never reach the browser;
- Lumi SQLite does not shadow-copy FreshRSS RSS data;
- Article HTML: transforms → DOMPurify as final boundary;
- Read/star writes use set semantics, not toggle;
- Pagination cursors remain opaque;
- Opening an article does not auto-mark it read.

---

## 3. Repository map

```text
apps/web/             React Web / PWA (TypeScript, Vite, Tailwind v4)
services/bff/         FastAPI BFF (Python)
docs/                 documentation (see docs/README.md)
tools/                progress dashboard
docker-compose.yml    FreshRSS + RSSHub dev services
```

---

## 4. Task workflow

1. Read `docs/README.md` (index) → task scope → affected files + tests;
2. `docs/explanation/architecture.md` only when touching data paths or
   boundaries; `docs/product/PRD.md` only when product scope is unclear;
3. Do NOT preload milestone history, `docs/research/`, upstream studies
   or reference repos unless the task specifically requires them;
4. Prefer exact symbol / component / directory search over broad scans;
   do not scan the repo, inspect or refactor unrelated modules;
5. Verification: targeted tests during development; full Web + BFF tests
   plus lint and build only at milestone Gate completion;
6. Once acceptance criteria are met → **STOP**. No autonomous adjacent
   refactoring, unrelated tests, or starting the next milestone.

---

## 5. Git and safety

- Never `reset --hard`, `clean -fd`, force push or overwrite user work;
- Do not create commits without explicit user approval;
- Keep changes scoped to the active task;
- Never commit `.env`, API credentials, FreshRSS/RSSHub secrets, AI keys,
  databases, browser profiles or private screenshots;
- Respect the current working tree and branch.

---

## 6. Security

- RSS/website content is untrusted — preserve the DOMPurify boundary;
- External links: safe protocols only, appropriate `rel` values;
- Do not mount Docker socket into the Web BFF;
- Future service-control adapters: allow-list, validate, no arbitrary commands.

---

## 7. Conventions

### Backend (Python/FastAPI)

- Typed request/response models; stable Lumi DTOs;
- Adapter errors → stable API errors; timeouts on all upstream calls;
- Bounded retries only for safe/idempotent operations;
- No secrets in logs; tests mock upstream network.

### Frontend (React/TypeScript)

- TanStack Query for server state; Zustand for lightweight UI state;
- No direct fetch to FreshRSS/RSSHub from browser;
- All network states need loading/empty/error UI;
- Semantic tokens, not hard-coded colors;
- Reusable primitives separate from domain components.

### UI architecture (Base UI foundation)

- Feature components MUST NOT import `@base-ui/react` directly;
  Base UI may only be used inside `components/ui/`;
- Reuse an existing Lumi UI primitive before creating a new one;
- Icon-only controls must use `IconButton` unless a documented
  exception exists (see design-system.md §19);
- Lumi Design Tokens (`--lumi-*`) are the visual source of truth;
- New modal/menu/popover/tooltip behavior must not be reimplemented
  manually — Base UI owns focus trap, Escape, dismissal, scroll lock,
  portal, positioning and ARIA;
- Do not introduce a second headless UI library (no shadcn, Radix,
  Headless UI, Ariakit, React Aria).

### Accessibility

- Visible keyboard focus; logical tab order;
- Icon-only controls have accessible labels;
- 44×44px minimum touch targets;
- Escape closes overlays; focus traps in dialogs/sheets;
- Reduced-motion preference respected.

### Build vs Reuse (long-term)

- Prefer upstream/framework capability before implementing infrastructure;
  boundaries and KEEP-justifications live in
  [docs/explanation/reuse-policy.md](docs/explanation/reuse-policy.md);
- Server API contracts must not be manually duplicated in Web — types are
  generated from OpenAPI (`pnpm api:generate` / `api:check`);
- Portable settings defaults/enums/bounds come from the generated
  settings metadata (`pnpm settings:generate` / `settings:check`), never
  hand-copied;
- Generated files must have deterministic generators and CI drift checks
  (`AUTO-GENERATED — DO NOT EDIT`);
- Base UI owns overlay/accessibility mechanics;
- BFF: ruff must stay clean (`uv run ruff check src tests scripts`);
  SQL stays an inline literal at each execute site;
- A new infrastructure dependency must reduce net maintenance complexity.

---

## 8. Definition of done

A task is complete only when:

1. Scope matches the approved spec/milestone;
2. Existing behavior is preserved or intentionally migrated;
3. Targeted tests pass and results are reported honestly;
4. No secrets or private data entered Git;
5. Documentation reflects actual implementation;
6. No commit/push/PR was made without user approval.
