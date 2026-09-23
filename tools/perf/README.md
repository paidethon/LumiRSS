# tools/perf — server-side load / soak

`load-soak.mjs` is a zero-dependency Node driver that puts an
authenticated, fixed-mix load (60% list / 20% detail / 10% search /
10% workspace add-remove) on the production-like e2e stack while
sampling the BFF container (`docker stats`, 1s interval, best-effort).
Methodology, metric definitions and engineering targets:
[docs/reference/performance.md](../../docs/reference/performance.md).

## Prerequisites

The e2e stack must be up and seeded (the fixture owner password is set
by the smoke's `up` step):

```bash
docker compose -f e2e/stack/docker-compose.e2e.yml up -d --build
e2e/stack/run-smoke.sh up     # seed owner password + FreshRSS install
e2e/stack/run-smoke.sh all    # optional: seed entries so detail/search have data
```

## Run

```bash
npm run perf:soak --  # or: node tools/perf/load-soak.mjs
DURATION_S=60 CONCURRENCY=3 node tools/perf/load-soak.mjs
```

Env (all optional, shown with defaults):

| Var | Default | Meaning |
|---|---|---|
| `BASE_URL` | `http://127.0.0.1:8088` | web/Caddy entry of the stack |
| `USERNAME` / `PASSWORD` | `owner` / `e2e-login-pwpw` | e2e fixture credentials (set by `run-smoke.sh up`, test fixture — not a real secret) |
| `DURATION_S` | `300` | steady (measured) phase length |
| `WARMUP_S` | `60` | warmup phase (discarded) |
| `CONCURRENCY` | `5` | parallel worker loops |
| `BFF_CONTAINER` | `lumirss-e2e-bff` | container sampled via `docker stats` |
| `SAMPLE_INTERVAL_MS` | `1000` | container stats interval |
| `REQUEST_TIMEOUT_MS` | `30000` | per-request timeout |
| `REPORT_DIR` | `tools/perf/reports` | JSON report output directory |

Exit codes: `0` clean run, `130` SIGINT (final report is still written),
`2` setup failure (stack down / bad credentials / seed missing).

Reports land in `tools/perf/reports/soak-<ts>.json` (local artifacts —
not generated code, safe to commit when they are gate evidence).

## Honesty rules

- Dev-box e2e numbers are a before/after baseline for THAT machine only;
  they are NOT measurements of the 2C/2G production target profile.
- Latency is client-observed (driver → Caddy → BFF), never labeled as
  server-side processing time.
- A passing soak only means "no degradation found in this scenario for
  this duration" — it does not promise the absence of leaks forever.
