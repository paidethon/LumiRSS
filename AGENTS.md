# LumiRSS Agent Guide

## 1. Purpose

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.
It combines FreshRSS, a project-owned FastAPI BFF, a three-pane React web
client, and optional on-demand summary and translation.

This file defines stable repository-wide instructions for coding agents.
Current task state belongs in the active GitHub Issue and its matching
`specs/<issue>/STATE.md`, not in this file.
These instructions guide agent behavior; permissions, hooks, GitHub access and
CI remain the enforcement layers.

## 2. Canonical naming

- Human-facing product and repository name: `LumiRSS`.
- When a language or tool requires a lowercase identifier, use `lumirss`.
- Do not introduce historical product names or repository names.
- New paths, examples, container labels, package names and documentation must
  follow this naming rule.

## 3. Sources of truth

For product and implementation decisions, use this order:

1. The current GitHub Issue and its explicit acceptance criteria.
2. The matching directory under `specs/`.
3. Accepted ADRs under `docs/ADR/`.
4. `contracts/openapi.yaml` for implemented HTTP API behavior.
5. `docs/PRD.md` for product scope and architecture.
6. `README.md` for human onboarding.

This file supplies repository-wide operating rules and architecture
invariants. If sources conflict, do not silently choose one. Report the exact
conflict and propose the smallest documentation correction.

## 4. Product scope

MVP includes:

- FreshRSS as the only RSS backend.
- Feed and category browsing.
- Entry listing, detail, cursor pagination, read state and starred state.
- A project-owned FastAPI BFF and React web client.
- User-triggered summary and translation with caching.
- Docker Compose startup, health checks, backup, restore and CI.

MVP excludes unless the current Issue explicitly changes scope:

- Folo private-backend compatibility on the production path.
- Miniflux or multiple RSS backends.
- Multi-user registration, OAuth and team permissions.
- Redis, Celery, RQ, vector databases and semantic search.
- Automatic daily digests, recommendations and social features.
- Multi-provider automatic AI routing.
- Native mobile applications and automatic production deployment.

## 5. Architecture invariants

- FreshRSS is the sole source of truth for feeds, categories, entries, read
  state, starred state, fetch history and OPML data.
- The BFF must not copy the complete FreshRSS entry database.
- BFF SQLite stores only LumiRSS-owned derived data such as summaries,
  translations, prompt/model metadata, request status and UI settings.
- The web client talks to the LumiRSS API contract, never directly to
  FreshRSS or the runtime AI provider.
- Qoder is a development tool, not a LumiRSS runtime AI provider.
- Folo compatibility belongs only in an isolated experiment and must not block
  the product path.
- External IDs are opaque strings. Do not parse, cast or infer structure from
  feed or entry IDs. URL-encode path values.
- List endpoints use opaque cursor pagination; do not expose offset assumptions.
- AI failure must never block normal feed and entry reading.
- Remote deployment should use HTTPS and same-origin routing for web and API.
- Credentials remain server-side. Use a FreshRSS API password, not the primary
  FreshRSS login password, for adapter access.
- `contracts/openapi.yaml`, once introduced, is the HTTP contract. API changes
  require contract, implementation and contract-test updates in the same PR.

## 6. Repository map

Paths may be introduced only when their Issue needs them:

- `apps/web/`: React, TypeScript and Vite web client.
- `services/bff/`: FastAPI BFF.
- `contracts/`: OpenAPI contract.
- `infra/`: Caddy, FreshRSS and backup configuration.
- `specs/`: issue-specific requirements, tasks and state.
- `experiments/folo-compat/`: isolated compatibility spike only.
- `docs/ADR/`: architecture decisions.
- `docs/runbooks/`: operational procedures.
- `.github/`: CI and contribution templates.
- `.lingma/rules/`: Qoder Desktop incremental rules only.

Do not create empty planned directories merely to match the PRD tree.
Do not create `.qoder/` until Qoder CLI is deliberately adopted.

## 7. Verified commands

Only list commands here after they exist and have been run successfully.
The currently verified checks are:

```bash
git status --short --branch
git diff --check
git diff --name-status
git diff --cached --check
```

Do not claim `make check`, pytest, Ruff, mypy, pnpm, Docker Compose or any
other tool works until the corresponding files and dependencies exist.
The PR that introduces a toolchain must add and verify its canonical commands
here and in `README.md`.

## 8. Working method

For each Issue:

1. Read this file, the Issue, its Spec, relevant ADRs and the API contract.
2. Inspect current code and tests before editing.
3. Summarize current behavior, target behavior, scope, exclusions, risks and a
   plan of no more than eight steps.
4. Work on one acceptance criterion at a time.
5. Prefer a failing test before implementation when executable behavior exists.
6. Make the smallest coherent change that satisfies the criterion.
7. Run the narrowest relevant checks, then the broader available checks.
8. Inspect `git diff` for scope, generated files, secrets and accidental edits.

Report verification as exactly one of:

- Passed
- Failed
- Not run
- Cannot verify

Never describe an expected or simulated result as Passed.

## 9. Engineering rules

- Python target is 3.12. Use type hints for public functions and async I/O for
  network operations.
- TypeScript should use strict typing. Avoid `any` unless a boundary is
  documented and validated.
- Keep domain models independent from FreshRSS response shapes.
- Convert upstream failures into stable domain or API errors.
- Set explicit connect and read timeouts for outbound HTTP.
- Retries must be bounded and limited to operations safe to retry.
- Validate AI structured output before persistence or display.
- Cache AI output using entry ID, content hash, provider, model, prompt version
  and language.
- Tests must cover success, boundary and failure behavior relevant to the
  change.
- Do not weaken tests, typing, lint or security checks merely to make CI pass.

Apply these rules only when the relevant code exists; do not scaffold unused
abstractions in advance.

## 10. Security and privacy

- Never read, print, commit or paste secret values, `.env` contents, databases,
  backups, logs, cookies, tokens or private keys.
- `.gitignore` and `.aiignore.md` reduce exposure but are not security
  boundaries.
- Keep examples fake and nonfunctional. `.env.example` contains variable names
  and empty values only.
- Redact credentials and sensitive query strings from logs and error messages.
- Original-article fetching must defend against SSRF, private and loopback
  addresses, DNS rebinding, redirect loops, oversized responses, non-text
  content, timeouts and malicious HTML.
- Do not add telemetry or send article content to a new external service without
  explicit Issue scope and documentation.
- If a possible secret is found, stop displaying it, report the path only, and
  ask the owner to rotate and remove it safely.

## 11. Git and external actions

- Preserve user changes and unrelated work.
- Do not discard, overwrite or rewrite history to resolve a dirty worktree.
- Keep each PR tied to one Issue and avoid opportunistic refactors.
- Do not commit generated runtime data or dependencies.
- Do not commit, push, merge, create or modify remote resources, deploy, or
  change access settings unless the user explicitly requests that action.
- Never use destructive Git commands or bypass permission prompts as a normal
  workflow.

## 12. Definition of done

A task is complete only when:

- Every acceptance criterion has evidence.
- Scope and architecture invariants remain intact.
- Relevant tests, lint, type checks and contract checks that actually exist
  have been run and their real results reported.
- Documentation and examples match the implemented behavior.
- The diff contains no unexpected files, secrets, debug output or unrelated
  changes.
- Failure and rollback behavior is documented when operational risk changes.
- `STATE.md` reflects evidence rather than intention.
- Remaining risks and unverified items are explicit.

## 13. Communication

- Lead with the outcome or blocker.
- Cite paths and command results for repository claims.
- Distinguish facts, inferences and recommendations.
- Ask before a change that materially expands scope, changes architecture,
  handles secrets, performs a destructive action or mutates an external system.
- Do not ask for confirmation when the current Issue already authorizes a safe,
  reversible local edit.

## 14. References

- Product requirements: `docs/PRD.md`
- Current work: GitHub Issue and matching `specs/` directory
- Architecture decisions: `docs/ADR/`
- API contract: `contracts/openapi.yaml`, once created
- Operations: `docs/runbooks/`, once created
