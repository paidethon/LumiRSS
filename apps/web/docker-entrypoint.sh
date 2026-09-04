#!/bin/sh
# Render the Caddyfile at container start:
# - both LUMIRSS_AUTH_USER and LUMIRSS_AUTH_HASH set  -> basic_auth enabled
# - neither set                                       -> no auth (trusted LAN)
# - exactly one set                                   -> FAIL LOUDLY (a half
#   configured auth would silently disable access control; spec says only
#   both-empty means no auth, anything else is an operator error)
set -eu

if [ -n "${LUMIRSS_AUTH_USER:-}" ] && [ -n "${LUMIRSS_AUTH_HASH:-}" ]; then
  sed "s|__AUTH_USER__|${LUMIRSS_AUTH_USER}|g; s|__AUTH_HASH__|${LUMIRSS_AUTH_HASH}|g" \
    /etc/caddy/Caddyfile.auth > /etc/caddy/Caddyfile
elif [ -z "${LUMIRSS_AUTH_USER:-}" ] && [ -z "${LUMIRSS_AUTH_HASH:-}" ]; then
  cp /etc/caddy/Caddyfile.noauth /etc/caddy/Caddyfile
else
  echo "FATAL: set BOTH LUMIRSS_AUTH_USER and LUMIRSS_AUTH_HASH, or neither." >&2
  exit 1
fi

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
