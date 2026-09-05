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
COPY package.json pnpm-lock.yaml* ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile.noauth /etc/caddy/Caddyfile.noauth
COPY Caddyfile.auth /etc/caddy/Caddyfile.auth
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
EXPOSE 80 443
ENTRYPOINT ["/docker-entrypoint.sh"]
