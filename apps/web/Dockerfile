# LumiRSS Web production image: React static build served by Caddy.
#
# Stage 1 builds the SPA; stage 2 serves dist/ with Caddy and reverse
# proxies /api/* to the BFF. Single-user access control (optional Caddy
# basic_auth) is rendered by docker-entrypoint.sh from LUMIRSS_AUTH_*.

FROM node:24-slim AS build
WORKDIR /app
# Build provenance for the About page (matches the BFF's GET /api/v1/version
# contract): --build-arg VITE_GIT_COMMIT=<git sha> from compose / CI.
ARG VITE_GIT_COMMIT=""
ENV VITE_GIT_COMMIT=${VITE_GIT_COMMIT}
# Bundle-guard mode passthrough (default empty = strict, exit 1 on
# overage). Only the e2e stack compose sets LUMIRSS_BUNDLE_GUARD=report
# so a known pre-existing baseline overage cannot block the cross-service
# smoke; the overage is still printed to the build log. CI/dev/release
# builds leave this unset.
ARG LUMIRSS_BUNDLE_GUARD=""
ENV LUMIRSS_BUNDLE_GUARD=${LUMIRSS_BUNDLE_GUARD}
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml* ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# caddy pinned by digest (same drift policy as freshrss/rsshub in compose):
# a stale floating `caddy:2-alpine` on registry mirrors built an image whose
# Caddy predates the `basic_auth` directive and crash-looped at start.
# 98eb57d… = caddy 2.11.4 (alpine).
FROM caddy:2-alpine@sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a
COPY --from=build /app/dist /srv
COPY Caddyfile.noauth /etc/caddy/Caddyfile.noauth
COPY Caddyfile.auth /etc/caddy/Caddyfile.auth
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
EXPOSE 80 443
ENTRYPOINT ["/docker-entrypoint.sh"]

# E06 real healthcheck (the image previously had NONE — `docker compose ps`
# reported "running" for a crash-looped Caddy, the exact failure the digest
# pin above was added for). The entrypoint appends an internal :9137 site
# serving the same /srv root, so this one probe proves BOTH that Caddy's
# HTTP stack answers AND that the static build artifact is served (grep the
# body for Vite's hashed /assets/ references; an empty or mis-mounted /srv
# fails the check). A dedicated port keeps it true in every mode: with a
# real DOMAIN the public :80 is a 308 auto-HTTPS redirect and https depends
# on ACME; in basic-auth mode public paths answer 401; Caddy has no built-in
# HTTP health endpoint. 9137 is never published by compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O - http://127.0.0.1:9137/index.html | grep -q "/assets/"
