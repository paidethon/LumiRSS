# LumiRSS

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader built around
FreshRSS, a project-owned FastAPI BFF, and a focused three-pane web interface.

## Status

Repository bootstrap. Application services are not implemented yet.

## Product principles

- FreshRSS is the only RSS source of truth.
- LumiRSS owns its API contract and web client.
- Summary and translation are user-triggered and optional.
- AI outages must not block normal reading.
- Data, deployment and backups remain under the owner's control.

## Current scope

The MVP covers subscriptions, entry reading, read/starred state, cursor
pagination, on-demand summary and translation, Docker Compose deployment,
health checks, backup, restore and CI.

Folo production compatibility, Miniflux, multi-user auth, Redis, task queues,
vector search, recommendations and native mobile apps are out of scope.

## Repository guidance

- Product requirements: `docs/PRD.md`
- Agent instructions: `AGENTS.md`
- Issue specifications: `specs/`
- Architecture decisions: `docs/ADR/`, when introduced
- API contract: `contracts/openapi.yaml`, when introduced

## Development

Application setup commands do not exist yet.
The current repository-only checks are:

```bash
git status --short --branch
git diff --check
git diff --name-status
git diff --cached --check
```

The Issue that introduces each toolchain must add its tested setup and check
commands here and in `AGENTS.md`.

## Security

Never commit environment files, credentials, runtime databases, backups or
logs. Copy `.env.example` only when an implementation Issue documents the
required setup.

## License

Not selected yet. Do not assume permission for redistribution until a license
is explicitly chosen.
