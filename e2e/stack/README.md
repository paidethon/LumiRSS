# e2e/stack/ — production-like E2E stack (test fixtures, not runtime services)

Everything in this directory exists ONLY for the release-gate smoke and
local/perf testing. It is **not** part of any deployment: production uses
`docker-compose.prod.yml` at the repo root, dev uses the root
`docker-compose.yml`. Nothing here runs unless you start it explicitly.

Contents:

| path | role |
|---|---|
| `docker-compose.e2e.yml` | Production-like compose topology (web/Caddy front, internal bff/freshrss/rsshub) plus the controlled test dependencies: the SMTP sink + HTTP inspector (the `mailpit` service, actually `mail_sink.py` standing in for Mailpit), the fixtures server, the scripted OpenAI-compatible server, and the read-only Obsidian vault. Mirrors prod so smoke results are release evidence. |
| `run-smoke.sh` | Drives the stack end to end; every check prints PASS/FAIL and the summary is the release verdict. Network-dependent checks SKIP honestly unless `LUMIRSS_E2E_ALLOW_NETWORK=1`. |
| `ai_server.py` | Scripted OpenAI-compatible server (deterministic AI answers; no real provider). |
| `mail_sink.py` | Minimal stdlib SMTP sink (:1025) + HTTP API (:8025, `GET /api/v1/messages`); mounted as the compose `mailpit` service so the stack works even where the Mailpit image cannot be pulled. |
| `fixtures/` | Files served by the controlled fixtures server: sample source payloads, a deliberately `malicious.html` sanitizer probe, `seed.json`, and a read-only Obsidian vault tree (note fixture `vault/AI/transformer.md` is fixture content, not project documentation). |

Quick start:

```bash
docker compose -f e2e/stack/docker-compose.e2e.yml up -d --build
e2e/stack/run-smoke.sh up   # init + smoke
```

All services bind 127.0.0.1 only; every credential in this tree is a
test fixture, never a real secret. Documentation: the test matrix lives
in [docs/development.md](../../docs/development.md); perf
usage of this stack in [tools/perf/README.md](../../tools/perf/README.md).
