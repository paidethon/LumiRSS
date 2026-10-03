# LumiRSS all-in-one image (R05 wave-0 skeleton): web SPA + BFF + FreshRSS
# (php-fpm) + RSSHub merged into ONE container, supervised by s6-overlay v3.
#
#   docker build -f docker/all-in-one/Dockerfile -t lumirss-allinone:<tag> .
#
# Build context is the REPO ROOT (web + bff sources). docker/all-in-one/
# Dockerfile.dockerignore keeps the context to those two source trees.
#
# Digest-pin policy (ARCH-06 parity with the per-service images): every base
# image and every COPY --from image is pinned tag@sha256 digest, and the
# s6-overlay / monolith release tarballs are pinned by published sha256.
# The five pins below are the EXACT digests docker-compose.prod.yml and the
# per-service Dockerfiles already pin (node/caddy from apps/web/Dockerfile,
# python from services/bff/Dockerfile, freshrss/rsshub from
# docker-compose.prod.yml), so the all-in-one image serves the same upstream
# code as the 4-container stack. Build-arg overrides are for LOCAL builds
# only (a dev machine behind a registry mirror that cannot resolve digests
# can pass the same-content local tag); CI MUST build with the defaults.
#
# Upgrade procedure: bump the digest here AND the matching pin in
# docker-compose.prod.yml / the per-service Dockerfiles in the same change.

# ---- pins (defaults = production; override only for local builds) ----------
ARG LUMIRSS_AIO_PYTHON_IMAGE=python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
ARG LUMIRSS_AIO_NODE_IMAGE=node:24-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
ARG LUMIRSS_AIO_FRESHRSS_IMAGE=freshrss/freshrss:1.29.1@sha256:ab6b363102ccdbc39f6a62db926f567c61a5289bf25ba460f1c34423d8cc1a4d
ARG LUMIRSS_AIO_RSSHUB_IMAGE=diygod/rsshub@sha256:387fd32ee2d8789154dcf6446a52365976e768d9ede1a7c1e610cf4da9d89fbc
ARG LUMIRSS_AIO_CADDY_IMAGE=caddy:2-alpine@sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a
# uv binary, same pin as services/bff/Dockerfile.
ARG LUMIRSS_AIO_UV_IMAGE=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d

# ---- stage: web SPA build (same steps as apps/web/Dockerfile stage 1) ------
FROM ${LUMIRSS_AIO_NODE_IMAGE} AS web-build
WORKDIR /app
ARG VITE_GIT_COMMIT=""
ENV VITE_GIT_COMMIT=${VITE_GIT_COMMIT}
ARG LUMIRSS_BUNDLE_GUARD=""
ENV LUMIRSS_BUNDLE_GUARD=${LUMIRSS_BUNDLE_GUARD}
COPY apps/web/package.json apps/web/pnpm-lock.yaml* apps/web/pnpm-workspace.yaml* ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY apps/web/ ./
RUN pnpm build

# The dist the runtime serves = the source build above. A workspace whose
# apps/web is mid-rebuild (does not typecheck) can substitute the last
# released dist WITHOUT changing this file:
#   docker build … --build-context web-dist=docker-image://ghcr.io/paidethon/lumirss/lumirss-web:2.8.0
# (the stage is replaced by that image's /srv; web-build is then unreferenced
# and skipped). CI never passes --build-context — releases always build
# from source.
FROM web-build AS web-dist
# Normalize the layout to /srv — the same path the lumirss-web image serves
# dist from, so the runtime COPY below works for both sources.
RUN cp -a /app/dist /srv

# ---- stages: external-image sources ----------------------------------------
# `COPY --from` cannot expand ARGs (docker/buildx#820), so every upstream
# image used in a COPY is re-declared here as a named stage. These FROMs do
# not run anything — they only pin which image content gets copied.
FROM ${LUMIRSS_AIO_UV_IMAGE} AS uv-src
FROM ${LUMIRSS_AIO_FRESHRSS_IMAGE} AS freshrss-src
FROM ${LUMIRSS_AIO_RSSHUB_IMAGE} AS rsshub-src
FROM ${LUMIRSS_AIO_CADDY_IMAGE} AS caddy-src

# ---- stage: BFF locked venv (same steps as services/bff/Dockerfile builder) -
FROM ${LUMIRSS_AIO_PYTHON_IMAGE} AS bff-deps
COPY --from=uv-src /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY services/bff/pyproject.toml services/bff/uv.lock ./
COPY services/bff/src ./src
COPY services/bff/scripts ./scripts
RUN uv sync --frozen --no-dev --no-editable --extra rag

# ---- runtime: ONE container, five s6 services ------------------------------
# Base = the SAME python:3.12-slim digest the BFF image uses (Debian 13
# trixie, python 3.12) so the copied venv is interpreter-identical, and the
# apt PHP is 8.4 — the exact same major/minor as the pinned
# freshrss/freshrss:1.29.1 image (PHP 8.4.21 on trixie, verified 2026-10-02).
FROM ${LUMIRSS_AIO_PYTHON_IMAGE}

# Build provenance, same contract as the per-service images.
ARG LUMIRSS_VERSION=""
ARG LUMIRSS_COMMIT=""

LABEL org.opencontainers.image.version="${LUMIRSS_VERSION}" \
      org.opencontainers.image.revision="${LUMIRSS_COMMIT}" \
      org.opencontainers.image.title="lumirss-allinone" \
      org.opencontainers.image.description="LumiRSS single-container stack: Caddy + FastAPI BFF + FreshRSS (php-fpm) + RSSHub under s6-overlay"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LUMIRSS_DB_PATH=/data/lumi.sqlite \
    LUMIRSS_COMMIT=${LUMIRSS_COMMIT} \
    PATH="/app/.venv/bin:$PATH" \
    # Caddy runs with no TLS (the host proxy terminates TLS), so it needs no
    # persistent storage; keep its state in tmp instead of a volume.
    XDG_DATA_HOME=/tmp/caddy-data \
    XDG_CONFIG_HOME=/tmp/caddy-config \
    # s6-overlay v3: a failed stage-2 (e.g. freshrss-init cannot prepare the
    # data volume) must kill the container so restart policy + healthcheck
    # surface it — never a green "running" with dead services.
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2

# --- system packages -------------------------------------------------------
# ca-certificates+curl: upstream HTTP + health probes; tzdata: CRON_MIN must
# tick in the deployment's local time (TZ), as the old freshrss container did.
# PHP 8.4 extensions mirror the official freshrss/freshrss:1.29.1 Debian
# image EXACTLY, minus what a single-sqlite all-in-one cannot use:
#   official: php-curl php-gmp php-intl php-mbstring php-xml php-zip
#             php-sqlite3 php-mysql php-pgsql (+ apache2/mod_php we replace
#             with php8.4-fpm; + libapache2-mod-auth-openidc, unused here)
#   here:     php8.4-{cli,fpm,curl,gmp,intl,mbstring,xml,zip,sqlite3,opcache}
#             (mysql/pgsql dropped: deployment is --db-type sqlite; see README)
# NOTE: apt has no per-package digest mechanism (unlike images/tarballs) —
# package integrity rests on the Debian repo signatures; the base image is
# digest-pinned above. Parity with the per-service images, which ship distro
# packages the same way.
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates curl tzdata xz-utils \
        php8.4-cli php8.4-fpm php8.4-curl php8.4-gmp php8.4-intl \
        php8.4-mbstring php8.4-xml php8.4-zip php8.4-sqlite3 php8.4-opcache \
    && rm -rf /var/lib/apt/lists/* \
    # Same PHP module disable list as the official FreshRSS Debian image
    # (phpdismod …). Missing modules are skipped silently — the list is a
    # superset of what trixie ships in mods-available.
    && for m in calendar exif ffi ftp gettext mysqli posix readline shmop \
                sockets sysvmsg sysvsem sysvshm xsl; do \
         phpdismod "$m" 2>/dev/null || true; \
       done \
    # php-fpm master + worker logs go to stderr (docker logs), like every
    # other service in this container. Inserted inside [global] — an append
    # would land after the pool.d include and be rejected as unknown entry.
    && sed -i '/^\[global\]$/a error_log = /proc/self/fd/2' /etc/php/8.4/fpm/php-fpm.conf

# --- s6-overlay v3 (PID1 + service supervision) ----------------------------
# Current release verified 2026-10-02; sha256 values are the official
# release-checksum file contents. amd64/x86_64 only — the published-images
# workflow is linux/amd64 (FIX-189 parity).
ARG S6_VERSION=3.2.3.2
ARG S6_SHA256_X86_64=e6befcc96a437a3831386ecfc51808c5d3e939dc5fe3c02ae9284599e8aa2408
ARG S6_SHA256_NOARCH=5379750ed30a84bbd2e2dd74847ba6b5bd29cd0b2e3ea2ec58049b57eb2eda12
ARG S6_SHA256_SYMLINKS=a215675c375aca9efecde3065df22b19fb8dcdc1362566931c6b5e778099a0fb
RUN set -eu; \
    mkdir -p /tmp/s6; cd /tmp/s6; \
    for f in s6-overlay-x86_64 s6-overlay-noarch s6-overlay-symlinks-noarch; do \
      curl -fsSL --retry 3 --retry-delay 2 -o "$f.tar.xz" \
        "https://github.com/just-containers/s6-overlay/releases/download/v${S6_VERSION}/$f.tar.xz"; \
    done; \
    echo "${S6_SHA256_X86_64}  s6-overlay-x86_64.tar.xz" | sha256sum -c -; \
    echo "${S6_SHA256_NOARCH}  s6-overlay-noarch.tar.xz" | sha256sum -c -; \
    echo "${S6_SHA256_SYMLINKS}  s6-overlay-symlinks-noarch.tar.xz" | sha256sum -c -; \
    tar -C / -Jxpf s6-overlay-x86_64.tar.xz; \
    tar -C / -Jxpf s6-overlay-noarch.tar.xz; \
    tar -C / -Jxpf s6-overlay-symlinks-noarch.tar.xz; \
    cd /; rm -rf /tmp/s6

# --- caddy: static Go binary from the SAME digest-pinned caddy image the web
# image uses (v2.11.4). Copied, not apt-installed, so the version pin is the
# digest above.
COPY --from=caddy-src /usr/bin/caddy /usr/local/bin/caddy

# --- rsshub: node runtime + full app tree from the digest-pinned rsshub
# image (node 24.20.0, glibc — same Debian 13 userland as this base).
# /app is the BFF's dir (/app/.venv), so rsshub lives at /app/rsshub.
COPY --from=rsshub-src /usr/local/bin/node /usr/local/bin/node
COPY --from=rsshub-src /app /app/rsshub

# --- FreshRSS application body (incl. its default data/ skeleton — an empty
# named volume is seeded from it on first mount, exactly like the old
# freshrss container seeded freshrss-data).
COPY --from=freshrss-src /var/www/FreshRSS /var/www/FreshRSS

# --- BFF: locked venv + ops scripts (parity with lumirss-bff runtime) ------
COPY --from=bff-deps /app/.venv /app/.venv
COPY --from=bff-deps /app/scripts /app/scripts

# P0-04: monolith (web snapshots) — same pinned release + checksum as
# services/bff/Dockerfile.
RUN set -eu; \
    case "$(uname -m)" in \
      x86_64) MONOLITH_URL=https://github.com/Y2Z/monolith/releases/download/v2.10.1/monolith-gnu-linux-x86_64; MONOLITH_SHA256=663ca914b078e91d5a854b4a07e913c613bbbcfe8fb11a24da1a6ab23c9205df ;; \
      aarch64) MONOLITH_URL=https://github.com/Y2Z/monolith/releases/download/v2.10.1/monolith-gnu-linux-aarch64; MONOLITH_SHA256=7f8cac6291b4015b24b964fcdf115a196abecc59e9149f7aa485175943f99997 ;; \
      *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    python -c "import urllib.request, sys; urllib.request.urlretrieve(sys.argv[1], '/tmp/monolith')" "$MONOLITH_URL"; \
    echo "$MONOLITH_SHA256  /tmp/monolith" | sha256sum -c -; \
    install -m 0755 /tmp/monolith /usr/local/bin/monolith; \
    rm /tmp/monolith

# --- SPA dist (parity with lumirss-web /srv) -------------------------------
COPY --from=web-dist /srv /srv

# --- s6 service tree, Caddyfile template, php pool, health helper ----------
COPY docker/all-in-one/rootfs/ /

# Rendered-at-start Caddy config template (Caddy -> bff X-Lumi-Token parity
# with apps/web/docker-entrypoint.sh; see caddy run script).
COPY docker/all-in-one/Caddyfile.aio.template /etc/caddy/Caddyfile.aio.template

# --- uid model (invariant, mirrors the 4-container stack) ------------------
# - bff:        uid 10001, primary gid 10001, supplementary gid 33 (www-data)
#               == old bff container's `USER lumirss` + `group_add: ["33"]`
#               (read-only traversal of FreshRSS data/users/<user>/ 0770
#               root:www-data for online backup preflight).
# - freshrss:   php-fpm workers run as www-data (33:33) — FreshRSS data stays
#               root:33/0664 owned exactly as the old freshrss container.
# - caddy:      root (binds the published :80; connects to the fpm socket).
# - rsshub:     uid 10001 (non-root, no freshrss group needed).
RUN set -eu; \
    useradd --create-home --uid 10001 lumirss; \
    usermod --append --groups www-data lumirss; \
    mkdir -p /data && chown lumirss:lumirss /data; \
    mkdir -p /app/rsshub/logs && chown -R lumirss:lumirss /app/rsshub/logs; \
    find /etc/s6-overlay/s6-rc.d /etc/s6-overlay/scripts -type f \
        \( -name run -o -name up -o -path '*/scripts/*' \) -exec chmod 0755 {} +; \
    chmod 0755 /usr/local/bin/lumirss-health

EXPOSE 80

VOLUME ["/data", "/var/www/FreshRSS/data"]

# Container health: Caddy HTTP stack + static SPA artifact (E06 parity,
# /healthz + Vite /assets/ refs) AND BFF liveness. The 90s start period
# covers first-boot freshrss-init (prepare.php) + uvicorn + rsshub cold start.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9137/healthz | grep -q ok \
      && curl -fsS http://127.0.0.1:9137/index.html | grep -q "/assets/" \
      && curl -fsS http://127.0.0.1:8000/health/live >/dev/null

ENTRYPOINT ["/init"]
