#!/bin/sh
# Render the Caddyfile at container start:
# - both LUMIRSS_AUTH_USER and LUMIRSS_AUTH_HASH set  -> basic_auth enabled
# - otherwise                                         -> no auth (trusted LAN)
set -eu

if [ -n "${LUMIRSS_AUTH_USER:-}" ] && [ -n "${LUMIRSS_AUTH_HASH:-}" ]; then
  sed "s|__AUTH_USER__|${LUMIRSS_AUTH_USER}|g; s|__AUTH_HASH__|${LUMIRSS_AUTH_HASH}|g" \
    /etc/caddy/Caddyfile.auth > /etc/caddy/Caddyfile
else
  cp /etc/caddy/Caddyfile.noauth /etc/caddy/Caddyfile
fi

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
