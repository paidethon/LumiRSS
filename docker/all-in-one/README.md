# LumiRSS all-in-one image

Single-container production topology: **Caddy + FastAPI BFF + FreshRSS
(php-fpm) + RSSHub** in one container, supervised by **s6-overlay v3**.
Wired end to end: image + compose verified locally, the `./lumirss` CLI
integration (`deploy --single` / `migrate-single` / `rollback-single`) is
landed, and `publish-images.yml` publishes `lumirss-allinone` to GHCR
(next to `lumirss-web` / `-bff`). Operator-facing runbook:
[docs/how-to/deploy.md](../../docs/how-to/deploy.md) §4b (decision record:
[docs/decisions/0008-single-container-topology.md](../../docs/decisions/0008-single-container-topology.md)).

```text
published (loopback)                    inside the container
127.0.0.1:18080 ──► :80  Caddy ───┬──► /srv           (React SPA, static)
   host TLS proxy                 ├──► /api,/feeds ──► 127.0.0.1:8000  BFF (uvicorn)
   terminates TLS                 └──► 127.0.0.1:8081 ─► unix socket  FreshRSS (php-fpm)
                                        127.0.0.1:8000 ◄── FreshRSS actualize (Atom feeds)
                                        127.0.0.1:12001  RSSHub (node)
```

## Files

| File | Purpose |
| --- | --- |
| `docker/all-in-one/Dockerfile` | Multi-stage build (digest-pinned bases; web dist + BFF venv built from source, FreshRSS/RSSHub/Caddy/node copied from the same digest-pinned upstream images the 4-container stack uses) |
| `docker/all-in-one/Dockerfile.dockerignore` | Build-context filter (context is the repo root; only `apps/web` + `services/bff` sources enter it) |
| `docker/all-in-one/Caddyfile.aio.template` | Rendered at container start from `LUMIRSS_INTERNAL_TOKEN` (same header_up contract as `apps/web/docker-entrypoint.sh`) |
| `docker/all-in-one/rootfs/etc/s6-overlay/s6-rc.d/` | Service tree: `freshrss-init` (oneshot) → `freshrss-php` + `freshrss-cron`; `bff`; `caddy` (after bff); `rsshub` |
| `docker/all-in-one/rootfs/usr/local/bin/lumirss-health` | Per-service status JSON (`docker exec lumirss-app lumirss-health`) |
| `docker-compose.allinone.yml` | Prebuilt-only single-service stack (no `build:` stanza, same policy as `docker-compose.prod.yml`) |

## Build (local/CI only — never on the production host)

Defaults inside the Dockerfile are the exact production digest pins (same
digests as `docker-compose.prod.yml` and the per-service Dockerfiles).
CI builds with defaults:

```sh
docker build -f docker/all-in-one/Dockerfile \
  --build-arg LUMIRSS_VERSION="$(cat VERSION)" \
  --build-arg LUMIRSS_COMMIT="$(git rev-parse HEAD)" \
  --build-arg VITE_GIT_COMMIT="$(git rev-parse HEAD)" \
  -t lumirss-allinone:<tag> .
```

On a dev box whose registry mirror cannot resolve digests, the same-content
local tags can be passed as overrides (NOT for release builds):

```sh
docker build -f docker/all-in-one/Dockerfile -t lumirss-allinone:dev \
  --build-arg LUMIRSS_AIO_PYTHON_IMAGE=python:3.12-slim \
  --build-arg LUMIRSS_AIO_NODE_IMAGE=node:24-slim \
  --build-arg LUMIRSS_AIO_FRESHRSS_IMAGE=freshrss/freshrss:1.29.1 \
  --build-arg LUMIRSS_AIO_RSSHUB_IMAGE=diygod/rsshub:latest \
  --build-arg LUMIRSS_AIO_CADDY_IMAGE=caddy:2-alpine \
  --build-arg LUMIRSS_AIO_UV_IMAGE=ghcr.io/astral-sh/uv:0.12.6 .
```

The pins are: `python:3.12-slim` (Debian 13 trixie — base for the BFF venv
AND this runtime, so the venv is interpreter-identical; trixie ships
PHP 8.4 = the same major/minor as `freshrss/freshrss:1.29.1`),
`node:24-slim` (SPA build stage only), `caddy` 2.11.4 (static Go binary,
copied), `freshrss/freshrss:1.29.1` (application body incl. its default
`data/` skeleton — an empty named volume is seeded from it, exactly like
the old freshrss container seeded `freshrss-data`), `diygod/rsshub`
(node 24.20.0 glibc + full `/app`). s6-overlay **v3.2.3.2** is downloaded
from the GitHub release and verified against the published sha256 values
(pinned in the Dockerfile); monolith v2.10.1 likewise (same pins as the
BFF image). apt packages (php8.4-*) cannot be digest-pinned — package
integrity rests on Debian repo signatures, same as the per-service images.

## Run

```sh
cp .env.prod.example .env.prod      # fill in secrets
docker compose -f docker-compose.allinone.yml up -d
docker compose -f docker-compose.allinone.yml ps        # one service, healthcheck
docker exec lumirss-app lumirss-health                   # per-service JSON
docker exec lumirss-app s6-svstat /run/s6-rc/servicedirs/caddy   # any service
```

Migration from the 4-container stack is the CLI's job:
`./lumirss migrate-single` (backup gate → pull gate → stop old stack
keeping volumes → start the single container → health + version
verification → persist `LUMIRSS_SINGLE=1`; `./lumirss rollback-single`
reverses it). Manual equivalent: `./lumirss backup` → stop old stack
(`docker compose -f docker-compose.prod.yml down`, NEVER `-v`) →
`docker compose -f docker-compose.allinone.yml up -d` → health checks. The
named volumes and project name (`lumirss-prod`) are identical, so
`lumi-data` / `freshrss-data` carry over unchanged.

## Ports

| Address | Service | Published? |
| --- | --- | --- |
| `:80` | Caddy — SPA + `/api` + `/feeds` | loopback only, `127.0.0.1:${LUMIRSS_UPSTREAM_PORT:-18080}` |
| `127.0.0.1:8081` | Caddy → php_fastcgi → FreshRSS UI + greader API | no (container loopback) |
| `127.0.0.1:12001` | RSSHub `PORT` (process binds container-wide; unreachable externally because only `:80` is published — same posture as the old internal-network container) | no |
| `127.0.0.1:8000` | BFF uvicorn | no |
| `:9137` | Caddy healthcheck site (E06 parity: no TLS/auth/redirect; serves `/srv`) | no |

The all-in-one image is **external-caddy-only**: it always serves plain
HTTP on `:80` for any Host header and never does ACME/TLS — the host
reverse proxy terminates TLS (`./lumirss caddy-config` renders its site
block). This is the only published shape of `docker-compose.allinone.yml`.

## Services (s6-rc)

| Service | Type | Runs as | Depends on | Notes |
| --- | --- | --- | --- | --- |
| `freshrss-init` | oneshot | root | — | TZ → php.ini, `cli/access-permissions.sh`, `cli/prepare.php` — the same steps the official FreshRSS entrypoint runs every start. Failure (S6_BEHAVIOUR_IF_STAGE2_FAILS=2) kills the container: a broken data volume is a hard error, not a green "running". |
| `freshrss-php` | longrun | root master / www-data workers | freshrss-init | php-fpm on `unix:/run/php/php8.4-fpm.sock`; pool budget in `pool.d/zz-lumirss.conf` (max_children 4, memory_limit 128M) |
| `freshrss-cron` | longrun | root loop / www-data php | freshrss-init | `LUMIRSS_FRESHRSS_CRON_MIN` (comma minute list, default `13,43`) → runs `su www-data -c 'php ./app/actualize_script.php'`, the exact command of the official image's crontab. flock prevents overlapping runs; **the one scheduling owner** (no cron daemon installed; unset = refresh disabled, same as upstream default) |
| `bff` | longrun | uid 10001 + gid 33 | freshrss-php | `uvicorn … --host 127.0.0.1 --port 8000 --no-access-log` |
| `caddy` | longrun | root | bff | renders Caddyfile then `caddy run`; token injection semantics ported from `apps/web/docker-entrypoint.sh` |
| `rsshub` | longrun | uid 10001 | — | `node dist/index.mjs` (the official image's start command), `MEMORY_MAX`, `NODE_OPTIONS` incl. `--max-http-header-size=32768` |

Dependency order: `freshrss-init → (freshrss-php, freshrss-cron) → bff →
caddy`. RSSHub is independent (AD-0018-3: it down only affects source
discovery/preview). SIGTERM (`docker stop`) → s6 stops services in reverse
dependency order, uvicorn/php-fpm/node exit gracefully; container exits
well within the 30s `stop_grace_period`.

## uid model (unchanged invariant)

| Paths | Owner | Written by |
| --- | --- | --- |
| `/data` (volume `lumi-data`) | `lumirss` 10001:10001 | BFF (control DB, secrets, backups) |
| `/var/www/FreshRSS/data` (volume `freshrss-data`) | root:www-data (33), user dirs 0770 root:33 | php-fpm workers (33), freshrss-init (root, via upstream access-permissions.sh) |
| BFF access to FreshRSS data | uid 10001 + supplementary gid 33 → read-only traversal for backup | — |

The bff user is `lumirss` (10001, supplementary `www-data`), replicating
the old container's `USER lumirss` + `group_add: ["33"]`.

## Volumes

Same names, same content, same project name (`lumirss-prod`) as the
4-container stack:

| Volume | Mount | Notes |
| --- | --- | --- |
| `lumi-data` | `/data` | control DB `lumi.sqlite`, per-user DBs, secrets, backups |
| `freshrss-data` | `/var/www/FreshRSS/data` | FreshRSS sqlite + config; empty volume is seeded from the image's copy of the upstream `data/` skeleton |

No separate `/freshrss-data:ro` mount: the BFF reads the FreshRSS data in
place (`FRESHRSS_DATA_DIR=/var/www/FreshRSS/data`). The `./lumirss backup`
flow (run-in-container python sqlite online-backup + `--user 0:0` file
tars) works against this image unchanged — it mounts the same-named
volumes into a throwaway container (`--entrypoint python3` /
default entry) and this image ships python3 + tar.

## Health

- **Container healthcheck** (`docker compose ps`): `:9137/healthz` must
  answer `ok` (Caddy HTTP stack up), `:9137/index.html` must contain the
  Vite `/assets/` refs (SPA artifact served), and BFF `/health/live` must
  answer (E06 + bff parity). `--start-period=90s` covers first boot
  (freshrss-init + uvicorn + rsshub cold start).
- **`lumirss-health`** prints per-service JSON: `state` (s6-svstat up/down),
  `pid`, `http_ok` (loopback probe: bff `/health/live`, rsshub `/healthz`,
  FreshRSS `8081/`), `last_actualize_epoch`, cgroup memory limit/used.
  Process-up vs interface-ok are reported separately; mapping them to the
  five-state service model is the consumer's (R03) job.

## Memory

Measured on the dev box (WSL2, x86_64, idle stack, fresh empty volumes,
`--memory 1200m`):

| | value |
| --- | --- |
| image (`docker image ls` SIZE) | **1.17 GB** (4-container stack images sum ≈ 1.68 GB: web 0.10 + bff 0.57 + freshrss 0.37 + rsshub 0.64) |
| idle container RSS (`docker stats`) | **~340 MiB** (28% of the 1200m limit) |
| cgroup `memory.used` (`lumirss-health`) | ~360–470 MB (includes page cache; RSS is the realistic floor) |
| SIGTERM → exit | **3.5 s** clean (exit 0), well inside docker's 10 s stop budget |

Compose default: `LUMIRSS_ALLINONE_MEM_LIMIT=1200m`,
`mem_reservation=256m` — sized for a 1.6 GB host. One cgroup holds all
four workloads, so a single runaway can OOM the whole container (s6
restarts the dead service; the RSSHub V8 heap cap
`LUMIRSS_RSSHUB_NODE_OPTIONS=--max-old-space-size=…` is the main
containment lever — set it if RSSHub dominates usage). Measure before
changing limits: `docker exec lumirss-app lumirss-health` (cgroup current)
or `docker stats lumirss-app`; never ship a limit that gets OOMKilled.

## Known limitations

- **RSSHub Chromium routes unavailable** — same as the current prod stack
  (the pinned `diygod/rsshub` image ships no Chromium; such routes were
  never usable).
- **Proxy basic-auth unsupported**: `LUMIRSS_AUTH_USER/LUMIRSS_AUTH_HASH`
  are warned about and ignored; access control = app session auth only
  (host TLS proxy may still add its own auth).
- **PHP is 8.4 from Debian trixie**, extensions mirror the official
  FreshRSS Debian image minus `php-mysql`/`php-pgsql` (this deployment is
  sqlite-only, `--db-type sqlite`). Re-adding them means one apt line.
- **amd64 only** (s6-overlay tarballs hardcoded x86_64) — matches the
  published-images workflow's `platforms: linux/amd64` (FIX-189).
- **One cgroup, one blast radius**: per-service memory isolation is weaker
  than the 4-container stack (mitigation: RSSHub heap cap + measured
  limits).
- **`.env.prod` carries stale internal hostnames** (`http://freshrss:80`,
  `http://rsshub:1200`) after migration — they are harmlessly overridden
  by the compose `environment:` block; leaving them is fine, cleaning them
  is fine.
- **Compose interpolation of `${LUMIRSS_UPSTREAM_PORT}` reads the shell /
  `.env`, not `.env.prod`** — same as `docker-compose.prod.yml`; `./lumirss`
  exports those values before invoking compose.
