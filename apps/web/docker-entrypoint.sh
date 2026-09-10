#!/bin/sh
# Render the Caddyfile at container start:
# - LUMIRSS_AUTH_MODE=session                  -> NO proxy-level auth; the
#   BFF owns login (bcrypt + long-lived session cookies). Static assets
#   and /api/v1/auth/* must be reachable pre-login, so Caddy adds nothing
#   here. LUMIRSS_AUTH_USER/HASH stay ignored in this mode.
# - both LUMIRSS_AUTH_USER and LUMIRSS_AUTH_HASH set  -> basic_auth enabled
# - neither set                                       -> no auth (trusted LAN)
# - exactly one set                                   -> FAIL LOUDLY (a half
#   configured auth would silently disable access control; spec says only
#   both-empty means no auth, anything else is an operator error)
# - LUMIRSS_INTERNAL_TOKEN set (non-empty)            -> inject a header_up
#   directive so every /api/* request forwarded to the BFF carries
#   X-Lumi-Token; the BFF (with the same token configured) rejects direct
#   in-network callers that bypass Caddy. Recommended: URL-safe charset.
# - LUMIRSS_EXTERNAL_CADDY set (non-empty)            -> site address ":80":
#   a reverse proxy on the host already owns 80/443, so this Caddy serves
#   plain HTTP for ANY Host header on its loopback-published port — no
#   ACME, no TLS, no http->https redirect inside the container.
set -eu

if [ -n "${LUMIRSS_EXTERNAL_CADDY:-}" ]; then
  SITE_ADDR=":80"
else
  SITE_ADDR="${DOMAIN:-localhost}"
fi

if [ "${LUMIRSS_AUTH_MODE:-basic}" = "session" ]; then
  TEMPLATE=/etc/caddy/Caddyfile.noauth
elif [ -n "${LUMIRSS_AUTH_USER:-}" ] && [ -n "${LUMIRSS_AUTH_HASH:-}" ]; then
  TEMPLATE=/etc/caddy/Caddyfile.auth
elif [ -z "${LUMIRSS_AUTH_USER:-}" ] && [ -z "${LUMIRSS_AUTH_HASH:-}" ]; then
  TEMPLATE=/etc/caddy/Caddyfile.noauth
else
  echo "FATAL: set BOTH LUMIRSS_AUTH_USER and LUMIRSS_AUTH_HASH, or neither." >&2
  exit 1
fi

TOKEN_DIRECTIVE=""
if [ -n "${LUMIRSS_INTERNAL_TOKEN:-}" ]; then
  case "${LUMIRSS_INTERNAL_TOKEN}" in
    *[!A-Za-z0-9._~+/=-]*)
      echo "FATAL: LUMIRSS_INTERNAL_TOKEN must be URL-safe (letters, digits, ._~+/=-)." >&2
      exit 1
      ;;
  esac
  TOKEN_DIRECTIVE="header_up X-Lumi-Token ${LUMIRSS_INTERNAL_TOKEN}"
fi

sed "s|__SITE_ADDR__|${SITE_ADDR}|g; \
     s|__AUTH_USER__|${LUMIRSS_AUTH_USER:-}|g; \
     s|__AUTH_HASH__|${LUMIRSS_AUTH_HASH:-}|g; \
     s|__INTERNAL_TOKEN_DIRECTIVE__|${TOKEN_DIRECTIVE}|g" \
  "$TEMPLATE" > /etc/caddy/Caddyfile

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
