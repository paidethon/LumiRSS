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
