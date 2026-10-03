# ADR 0008 — Optional Single-Container Production Topology

Status: Accepted

## Context

The production shape so far was four containers (web/Caddy, bff,
freshrss, rsshub) with digest-pinned GHCR images. It isolates workloads
well, but on the small self-hosts LumiRSS explicitly targets
(~1.6 GB RAM VPS) it means four images to pull, four lifecycle surfaces
to watch, and a compose file set whose overlays (external-caddy,
obsidian, build) newcomers must understand before their first deploy.
The services themselves already talk over short, fixed paths — the
four-container split is an operations choice, not a data-model
requirement: the same named volumes and uid model work whichever way the
processes are arranged.

## Decision

1. **One optional all-in-one image, same parts.**
   `lumirss-allinone` runs **Caddy + FastAPI BFF + FreshRSS (php-fpm) +
   RSSHub** in a single container supervised by s6-overlay v3. The
   multi-stage build reuses the exact same digest-pinned upstream images
   and version pins as the 4-container stack; the BFF venv interpreter
   is identical to the bff image's.
2. **Prebuilt-only, published like the others.**
   `docker-compose.allinone.yml` has no `build:` stanza (same policy as
   `docker-compose.prod.yml`) and `publish-images.yml` pushes the image
   to GHCR next to `lumirss-web` / `-bff`, with its digest in the same
   `release-manifest.json`. amd64-only (s6-overlay tarballs are x86_64
   pinned) — matching the existing platform matrix.
3. **The data model invariants are unchanged.** Compose project name
   (`lumirss-prod`), named volumes (`lumi-data`, `freshrss-data`) and
   the uid model (BFF `lumirss` 10001 + supplementary gid 33, FreshRSS
   www-data 33) are identical to the 4-container stack. A data volume
   set runs under either topology unchanged, and `./lumirss backup` /
   `restore` work against both.
4. **External-caddy-only by construction.** The container publishes only
   `127.0.0.1:${LUMIRSS_UPSTREAM_PORT:-18080} -> 80` (plain HTTP); the
   host reverse proxy terminates TLS (`./lumirss caddy-config` renders
   its site block). FreshRSS/RSSHub/BFF stay on container loopback,
   never published. `--single` and `--external-caddy` are mutually
   exclusive because the former implies the latter.
5. **App session is the only access control here.** The proxy-level
   basic-auth keys (`LUMIRSS_AUTH_USER/HASH`) are ignored with a
   warning; access control is the application's session auth
   (`LUMIRSS_AUTH_MODE=session`) — consistent with session being the
   primary mode overall.
6. **CLI-first lifecycle with a real rollback point.**
   `./lumirss deploy --single` for fresh installs;
   `./lumirss migrate-single` snapshots a rollback point from the
   *running* 4-container stack before touching anything (env copy +
   previous image tag + running image IDs + pre-migration schema
   version), then walks backup gate → pull gate (a pull failure never
   stops the old stack) → `down` old stack (never `-v`) → up single
   container → health check → version/image self-proof → persist
   `LUMIRSS_SINGLE=1`. `./lumirss rollback-single` consumes the rollback
   point in reverse; if the schema moved forward under the newer image,
   it says so and requires explicit confirmation or a pre-migration
   backup restore instead of pretending images can undo migrations.
   `status` / `doctor` / `update` reuse the persisted topology.
7. **Sized for one cgroup, measured, not guessed.** Default
   `LUMIRSS_ALLINONE_MEM_LIMIT=1200m` (reservation 256m) fits a 1.6 GB
   host; the idle stack measured ~340 MiB RSS on the dev box. The RSSHub
   V8 heap cap remains the main containment lever, and the docs say:
   measure before changing limits.

## Consequences

- **Weaker blast-radius isolation.** Four workloads share one cgroup; a
  single runaway service can OOM the whole container (s6 restarts the
  dead service, but neighbors suffer). That is the accepted trade for
  fewer moving parts on small hosts — the 4-container stack remains the
  default and the recommended shape when memory headroom exists.
- **Both directions stay honest.** Migration keeps volumes (nothing is
  copied or rewritten), rollback is a topology switch — but a control-DB
  schema that moved forward under a newer image cannot be undone by old
  images; the CLI refuses or double-confirms there and points at backup
  restore.
- **One published surface.** Operators get one loopback port and one
  host-proxy site block instead of a compose file set; the internal
  service names (`http://freshrss`, `http://rsshub`) simply do not exist
  in this topology, and stale `.env.prod` hostnames are harmlessly
  overridden.
