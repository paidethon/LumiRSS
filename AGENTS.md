# AGENTS.md — LumiRSS Agent Working Agreement

> For ZCode, Codex, Claude Code, Cursor, Qoder, OpenCode and similar
> coding agents. Durable rules only — verify against the actual
> repository state before relying on anything.

---

## 1. Project identity

LumiRSS is an invite-based multi-account, self-hosted, source-first
information reader: RSS/Atom via FreshRSS, non-RSS via RSSHub, a FastAPI
BFF, and a responsive React Web / PWA client. The operator invites
members from the admin console; each invitee activates their own account
(one-time, expiring invite → self-chosen username/password at
`/activate`), and every account's data is fully isolated (control DB +
per-user DBs, server-derived identity). Public registration is an
optional, default-off instance policy. Feature status lives in
[docs/roadmap.md](docs/roadmap.md); released work in `CHANGELOG.md`.

NOT implemented — do not describe these as existing: web clipping
browser extension, free-form Obsidian write-back (the read-side vault
projection stays read-only; the only write face is the separately
mounted, hard-bounded server-side export directory), MCP surface, PWA
push / background sync, multi-tenant tenancy. LumiRSS is small-scale by
design; public-internet hardening is out of scope. All data-protection
rules below still apply exactly as written.

## 2. Architecture invariants (non-negotiable)

- FreshRSS owns RSS-domain state (feeds, entries, read/star); Lumi
  SQLite never shadow-copies RSS data (the derived, rebuildable search
  projection is the only exception);
- Web client talks only to the Lumi BFF (`/api/v1/*`); upstream
  credentials and secrets never reach the browser;
- RSSHub is an upstream feed generator, not the entry database;
- Article HTML: controlled transforms → DOMPurify as the final boundary;
- Read/star writes use set semantics, not toggle; pagination cursors
  stay opaque; opening an article does not auto-mark it read;
- Server-side URL fetching: http/https only, validate host, reject
  loopback/private/reserved addresses (explicit allow-list key excepted).

Full explanation: [docs/architecture.md](docs/architecture.md).

## 3. Where to look

| Task | Read |
|---|---|
| Any task | This file + the 1–2 domain docs below — nothing else by default |
| Deploy/upgrade/backup/troubleshoot | [docs/operations.md](docs/operations.md) |
| Config keys/defaults | [docs/configuration.md](docs/configuration.md) |
| Data paths, boundaries, account isolation | [docs/architecture.md](docs/architecture.md) |
| UI work | [docs/design-system.md](docs/design-system.md) |
| Tests, CI, codegen, docs governance | [docs/development.md](docs/development.md) |
| Feature status / what's next | [docs/roadmap.md](docs/roadmap.md) |

Docs index: https://doc.oouo.top/ (built from `docs/`).

## 4. Documentation rules

- **默认禁止创建新的 Markdown 文档。** If the information fits an
  existing SSOT, update that document instead. New long-term docs require
  proof that no existing owner can carry the content, plus an explicit
  ALLOWLIST entry in `scripts/check_docs_allowlist.py` (CI enforces).
- One fact, one authoritative owner. Fix facts in code/tests first, then
  in the owning doc; link instead of copying.
- Chat history, old task prompts, old audits, recovery notes and past
  plans never override the current code, tests and authoritative docs.
  History lives in Git, not in the tree.
- `docs/upstream/` is a LEGAL archive (license/attribution) — do not
  turn it into a narrative section or nav entry.
- Machine-readable files (`docs/*.json`) have their own gates — never
  hand-edit around them; `docs/release-notes.json` is consumed by the
  running BFF and must not be moved.

## 5. Task workflow

1. `docs/roadmap.md` for scope → affected files + tests;
2. `docs/architecture.md` only when touching data paths or boundaries;
3. Do NOT preload milestone history, old PRDs, audits or upstream
   research — they are deleted on purpose; Git history has them;
4. Prefer exact symbol search over broad scans; do not refactor
   unrelated modules;
5. Targeted tests during development; full Web + BFF tests + lint +
   build only at milestone gates;
6. Acceptance criteria met → **STOP**. No autonomous adjacent work.

## 6. Conventions

### Backend (Python/FastAPI)

Typed request/response models; stable Lumi DTOs; adapter errors →
stable API errors; timeouts on all upstream calls; bounded retries only
for safe/idempotent operations; no secrets in logs; tests mock upstream
network; ruff stays clean; SQL stays an inline literal at each execute
site.

### Frontend (React/TypeScript)

TanStack Query for server state; Zustand for lightweight UI state; no
direct fetch to FreshRSS/RSSHub from the browser; every network state
needs loading/empty/error UI; semantic tokens, not hard-coded colors;
reusable primitives live in `components/ui/`.

### UI architecture (Base UI foundation)

Feature components MUST NOT import `@base-ui/react` directly — only
`components/ui/` may. Reuse an existing Lumi UI primitive before creating
a new one. Icon-only controls use `IconButton`. `--lumi-*` tokens are the
visual source of truth. Overlay mechanics (focus trap, Escape,
dismissal, scroll lock, portal, positioning, ARIA) are owned by Base UI —
never reimplement manually. No second headless UI library (no shadcn,
Radix, Headless UI, Ariakit, React Aria).

### Accessibility

Visible keyboard focus; logical tab order; icon-only controls have
accessible labels; 44×44px minimum touch targets; Escape closes
overlays; focus traps in dialogs/sheets; reduced-motion respected.

### Build vs Reuse

Prefer upstream/framework capability before implementing infrastructure.
Server API contracts are never hand-duplicated in Web — types are
generated (`pnpm api:generate` / `api:check`); portable settings
defaults/enums/bounds come from generated settings metadata
(`pnpm settings:generate` / `settings:check`). Generated files carry
`AUTO-GENERATED — DO NOT EDIT` and CI drift checks. Details:
[docs/development.md](docs/development.md).

## 7. Git and safety

- Never `reset --hard`, `clean -fd`, force push or overwrite user work;
- No commits/pushes/PRs without explicit user approval;
- Keep changes scoped to the active task;
- Never commit `.env`, API credentials, FreshRSS/RSSHub secrets, AI
  keys, databases, browser profiles or private screenshots.

## 8. Security

RSS/website content is untrusted — preserve the DOMPurify boundary;
external links: safe protocols only, appropriate `rel` values; no Docker
socket in the Web BFF; future service-control adapters: allow-list,
validate, no arbitrary commands.

## 9. Definition of done

1. Scope matches the approved spec/milestone;
2. Existing behavior preserved or intentionally migrated;
3. Targeted tests pass and results are reported honestly;
4. No secrets or private data entered Git;
5. Documentation reflects actual implementation (owning SSOT updated);
6. No commit/push/PR was made without user approval.
