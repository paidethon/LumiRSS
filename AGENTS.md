# AGENTS.md — LumiRSS Agent Working Agreement

> For Qoder, Codex, Claude Code, Cursor, OpenCode and similar coding agents.
> This file contains durable rules, not project encyclopedia.
> Verify against actual repository state before relying on it.

---

## 1. Project identity

LumiRSS is a single-user, self-hosted, source-first information reader under
active MVP development. Current scope: RSS/Atom via FreshRSS, non-RSS via
RSSHub, FastAPI BFF, responsive React Web / PWA.

Implemented (verify against source before relying on this list): AI summary,
translation and article conversation plus AI settings (0015–0017); RSSHub
source discovery and control; unified settings center; backup / restore and
operations (0018); Caddy-fronted production deployment (0018–0019).

NOT implemented — do not describe these as existing: web clipping, Obsidian
integration, and other explicitly deferred Phase-2 features. LumiRSS is
single-user by design (one trusted user behind the operator's own auth /
network); multi-user tenancy and public-internet hardening are out of scope.

---

## 2. Architecture invariants

These are non-negotiable. Full explanation: [architecture/README.md](docs/architecture/README.md).

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

## 4. Documentation routing

Start here for any task:

1. Read `docs/README.md` (navigation index);
2. Read the **active milestone** document;
3. Read directly affected source files and tests;
4. Read `docs/architecture/` only when touching data paths or boundaries;
5. Read `docs/product/PRD.md` only when product scope is unclear;
6. Do NOT read completed milestones, upstream studies or reference repos
   unless the task specifically requires them.

---

## 5. Scope discipline

```text
- Do not scan the entire repository unless the task genuinely requires it.
- Prefer targeted file search over broad exploration.
- Do not inspect unrelated modules.
- Do not refactor unrelated code.
- Do not reread completed milestone history for ordinary work.
- Do not inspect upstream reference repositories unless explicitly required.
- Stop once acceptance criteria are satisfied.
```

---

## 6. Verification discipline

During development:

```text
affected tests only (targeted)
```

At milestone Gate completion:

```text
full Web tests + full BFF tests + lint + build
```

Do not run full test suites for ordinary CSS or small UI changes.

---

## 7. Git and safety

- Never `reset --hard`, `clean -fd`, force push or overwrite user work;
- Do not create commits without explicit user approval;
- Keep changes scoped to the active task;
- Never commit `.env`, API credentials, FreshRSS/RSSHub secrets, AI keys,
  databases, browser profiles or private screenshots;
- Respect the current working tree and branch.

---

## 8. Security

- RSS/website content is untrusted — preserve the DOMPurify boundary;
- External links: safe protocols only, appropriate `rel` values;
- Do not mount Docker socket into the Web BFF;
- Future service-control adapters: allow-list, validate, no arbitrary commands.

---

## 9. Conventions

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

### Accessibility

- Visible keyboard focus; logical tab order;
- Icon-only controls have accessible labels;
- 44×44px minimum touch targets;
- Escape closes overlays; focus traps in dialogs/sheets;
- Reduced-motion preference respected.

---

## 10. Efficient agent workflow

### Task start

Read only:
```text
AGENTS.md → docs/README.md → active milestone → affected files + tests
```

### Do not preload

```text
completed milestones · PRD · full architecture · upstream studies
reference repos · full git history · unrelated modules
```

### Search strategy

Prefer exact symbol / component / directory over broad scan.

### Stop condition

Once acceptance criteria are met → **STOP**. Do not autonomously refactor
adjacent code, run unrelated tests, or continue to the next milestone.

---

## 11. Definition of done

A task is complete only when:

1. Scope matches the approved spec/milestone;
2. Existing behavior is preserved or intentionally migrated;
3. Targeted tests pass and results are reported honestly;
4. No secrets or private data entered Git;
5. Documentation reflects actual implementation;
6. No commit/push/PR was made without user approval.
