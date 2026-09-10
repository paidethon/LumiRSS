#!/usr/bin/env bash
# Deploy-lifecycle tests (no cluster required):
#   - compose renders for full-stack AND external host-Caddy mode
#   - external mode binds loopback-only and publishes nothing else
#   - web entrypoint renders the site address per mode (":80" vs DOMAIN),
#     inside the real caddy:2-alpine image with a stub `caddy`
#   - preflight port-conflict + caddy-config snippet + configure idempotency
#   - doctor / update run to completion against a stub docker CLI
# Run from anywhere: tests/deploy/run-deploy-tests.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

ok()  { printf '  ok   %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n' "$1"; FAIL=$((FAIL + 1)); }

assert_eq() { # desc expected actual
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 — expected [$2] got [$3]"; fi
}
assert_contains() { # desc needle haystack
  if [[ "$3" == *"$2"* ]]; then ok "$1"; else bad "$1 — missing [$2]"; fi
}
assert_not_contains() { # desc needle haystack
  if [[ "$3" != *"$2"* ]]; then ok "$1"; else bad "$1 — unexpected [$2]"; fi
}

new_sandbox() { # isolated copy so tests never touch a developer .env.prod
  local dir; dir="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-test.XXXXXX")"
  cp "$REPO_ROOT/lumirss" "$dir/"
  cp "$REPO_ROOT/docker-compose.prod.yml" "$REPO_ROOT/docker-compose.external-caddy.yml" "$dir/"
  cp "$REPO_ROOT/.env.prod.example" "$dir/.env.prod.example"
  mkdir -p "$dir/web"
  cp "$REPO_ROOT/apps/web/docker-entrypoint.sh" "$REPO_ROOT/apps/web/Caddyfile.auth" \
    "$REPO_ROOT/apps/web/Caddyfile.noauth" "$dir/web/"
  printf '%s\n' "$dir"
}

render_json() { # render compose config as JSON for the given mode
  local dir="$1" mode="$2"
  (cd "$dir" && cp -f .env.prod.example .env.prod
   if [[ "$mode" == "external" ]]; then
     LUMIRSS_EXTERNAL_CADDY=1 LUMIRSS_UPSTREAM_PORT=18080 \
       docker compose -f docker-compose.prod.yml -f docker-compose.external-caddy.yml \
       config --format json
   else
     docker compose -f docker-compose.prod.yml config --format json
   fi) 2>/dev/null
}

ports_summary() { # canonical "host_ip:published:target" list for a service
  python3 -c '
import json, sys
cfg = json.load(sys.stdin)
svc = sys.argv[1]
out = sorted(
    "{}:{}:{}".format(p.get("host_ip", ""), p.get("published", ""), p.get("target", ""))
    for p in (cfg["services"][svc].get("ports") or [])
)
print(";".join(out))
' "$1"
}

web_env() { # environment value for a key from a rendered config
  python3 -c '
import json, sys
cfg = json.load(sys.stdin)
print(cfg["services"]["web"].get("environment", {}).get(sys.argv[1], ""))
' "$1"
}

# ---------------------------------------------------------------------------
echo "== 1. compose render: full-stack mode =="
if docker compose version >/dev/null 2>&1; then
  sb="$(new_sandbox)"
  assert_eq "full-stack: web publishes 0.0.0.0:80 + 0.0.0.0:443" \
    ":443:443;:80:80" \
    "$(render_json "$sb" full | ports_summary web)"
  assert_not_contains "full-stack: web is NOT loopback-pinned" "127.0.0.1" \
    "$(render_json "$sb" full | ports_summary web)"
  assert_not_contains "full-stack: LUMIRSS_EXTERNAL_CADDY unset" \
    '"LUMIRSS_EXTERNAL_CADDY": "1"' "$(render_json "$sb" full)"
  rm -rf "$sb"
else
  bad "docker compose not available — render tests cannot run"
fi

# ---------------------------------------------------------------------------
echo "== 2. compose render + loopback bind: external-caddy mode =="
if docker compose version >/dev/null 2>&1; then
  sb="$(new_sandbox)"
  cfg="$(render_json "$sb" external)"
  assert_eq "external: web port is exactly 127.0.0.1:18080->80" \
    "127.0.0.1:18080:80" "$(printf '%s' "$cfg" | ports_summary web)"
  assert_eq "external: LUMIRSS_EXTERNAL_CADDY=1 reaches the web container" \
    "1" "$(printf '%s' "$cfg" | web_env LUMIRSS_EXTERNAL_CADDY)"
  for svc in bff freshrss rsshub; do
    assert_eq "external: $svc publishes nothing" "" \
      "$(printf '%s' "$cfg" | ports_summary "$svc")"
  done
  rm -rf "$sb"
fi

# ---------------------------------------------------------------------------
echo "== 3. entrypoint site address rendering (caddy:2-alpine) =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/caddy" <<'STUB'
#!/bin/sh
# print the rendered Caddyfile instead of starting caddy
[ "$1" = "run" ] && exec cat "$3"
exit 0
STUB
chmod +x "$stub_dir/caddy"
if docker image inspect caddy:2-alpine >/dev/null 2>&1 || docker pull -q caddy:2-alpine >/dev/null 2>&1; then
  run_ep() { # run_ep [env assignments…] -> rendered Caddyfile from the stub
    local etc out rc
    etc="$(mktemp -d)"
    out="$(docker run --rm \
      -v "$sb/web":/web:ro \
      -v "$sb/web/Caddyfile.auth":/etc/caddy/Caddyfile.auth:ro \
      -v "$sb/web/Caddyfile.noauth":/etc/caddy/Caddyfile.noauth:ro \
      -v "$etc":/etc/caddy -v "$stub_dir":/stub:ro \
      -e PATH="/stub:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
      "$@" --entrypoint /bin/sh caddy:2-alpine /web/docker-entrypoint.sh 2>/dev/null)"
    rc=$?
    rm -rf "$etc"
    printf '%s' "$out"
    return "$rc"
  }
  site_addr() { # first non-comment, non-blank line of the rendered config
    run_ep "$@" 2>/dev/null | sed -e '/^#/d' -e '/^[[:space:]]*$/d' | head -1
  }
  assert_eq "entrypoint: default -> localhost" \
    "localhost {" "$(site_addr)"
  assert_eq "entrypoint: DOMAIN wins" \
    "reader.example.com {" "$(site_addr -e DOMAIN=reader.example.com)"
  assert_eq "entrypoint: external mode -> :80 any-host" \
    ":80 {" "$(site_addr -e LUMIRSS_EXTERNAL_CADDY=1 -e DOMAIN=ignored.example.com)"
  if run_ep -e LUMIRSS_AUTH_USER=only >/dev/null 2>&1; then
    bad "entrypoint: half-configured auth must fail loudly"
  else
    ok "entrypoint: half-configured auth fails loudly"
  fi
  auth_out="$(run_ep -e LUMIRSS_AUTH_USER=op '-eLUMIRSS_AUTH_HASH=$$2b$$12$$x' -e LUMIRSS_EXTERNAL_CADDY=1)"
  assert_contains "entrypoint: auth template keeps basic_auth" "basic_auth" "$auth_out"
  assert_contains "entrypoint: auth template still uses :80 in external mode" ':80 {' "$auth_out"
else
  bad "caddy:2-alpine unavailable — entrypoint tests cannot run"
fi
rm -rf "$sb" "$stub_dir"

# ---------------------------------------------------------------------------
echo "== 4. preflight port-conflict (external mode) =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/ss" <<'STUB'
#!/bin/sh
# fake listener table: $LUMIRSS_TEST_OCCUPIED=1 -> port 18080 in use
if [ "${LUMIRSS_TEST_OCCUPIED:-0}" = "1" ]; then
  printf 'LISTEN 0      4096          0.0.0.0:18080      0.0.0.0:*\n'
fi
exit 0
STUB
chmod +x "$stub_dir/ss"
conflict_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_OCCUPIED=1 LUMIRSS_DOMAIN=reader.example.com \
     ./lumirss deploy --external-caddy --dry-run 2>&1)"
rc=$?
assert_eq "preflight fails on a foreign occupied upstream port" "1" "$rc"
assert_contains "preflight names the offending port and fix" "set LUMIRSS_UPSTREAM_PORT" "$conflict_out"
rm -rf "$stub_dir"

# ---------------------------------------------------------------------------
echo "== 5. dry-run deploy (external) + caddy-config snippet =="
sb="$(new_sandbox)"
dry_out="$(cd "$sb" && env LUMIRSS_DOMAIN=reader.example.com LUMIRSS_AUTH_USER=op LUMIRSS_IMAGE_TAG=cc627f48ca4e \
  ./lumirss deploy --external-caddy --dry-run 2>&1)"
rc=$?
assert_eq "dry-run external deploy succeeds" "0" "$rc"
assert_contains "dry-run renders compose config" "compose config renders OK" "$dry_out"
assert_contains ".env.prod persisted external mode" "LUMIRSS_EXTERNAL_CADDY=1" "$(cat "$sb/.env.prod")"
assert_contains ".env.prod persisted upstream port" "LUMIRSS_UPSTREAM_PORT=18080" "$(cat "$sb/.env.prod")"
assert_contains ".env.prod persisted deployed image tag" "LUMIRSS_IMAGE_TAG=cc627f48ca4e" "$(cat "$sb/.env.prod")"
snippet="$(cd "$sb" && ./lumirss caddy-config 2>&1)"
assert_contains "snippet has BEGIN marker" "# BEGIN LUMIRSS" "$snippet"
assert_contains "snippet has END marker" "# END LUMIRSS" "$snippet"
assert_contains "snippet proxies the domain" "reader.example.com {" "$snippet"
assert_contains "snippet targets loopback port" "reverse_proxy 127.0.0.1:18080" "$snippet"

# ---------------------------------------------------------------------------
echo "== 6. deploy idempotency (second run keeps secrets/port) =="
token_1="$(grep '^LUMIRSS_INTERNAL_TOKEN=' "$sb/.env.prod")"
user_1="$(grep '^LUMIRSS_AUTH_USER=' "$sb/.env.prod")"
tag_1="$(grep '^LUMIRSS_IMAGE_TAG=' "$sb/.env.prod")"
(cd "$sb" && env LUMIRSS_DOMAIN=reader.example.com LUMIRSS_AUTH_USER=op \
  ./lumirss deploy --external-caddy --dry-run >/dev/null 2>&1)
assert_eq "token unchanged after second deploy" "$token_1" "$(grep '^LUMIRSS_INTERNAL_TOKEN=' "$sb/.env.prod")"
assert_eq "auth user unchanged" "$user_1" "$(grep '^LUMIRSS_AUTH_USER=' "$sb/.env.prod")"
assert_eq "image tag unchanged (no env on re-run)" "$tag_1" "$(grep '^LUMIRSS_IMAGE_TAG=' "$sb/.env.prod")"
assert_contains "port unchanged" "LUMIRSS_UPSTREAM_PORT=18080" "$(cat "$sb/.env.prod")"
rm -rf "$sb"

# ---------------------------------------------------------------------------
echo "== 7. doctor + update against a stub docker CLI =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# stub docker: everything succeeds, compose subcommands answer sanely
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  inspect) echo healthy;;
  ps) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      pull) echo " Pulled";;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
doctor_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && printf 'DOMAIN=reader.example.com\nLUMIRSS_EXTERNAL_CADDY=1\nLUMIRSS_UPSTREAM_PORT=18080\n' >> .env.prod \
  && env PATH="$stub_dir:$PATH" ./lumirss doctor 2>&1)"
rc=$?
assert_eq "doctor exits 0 (WARN-only) with stub docker" "0" "$rc"
assert_not_contains "doctor reports no FAIL lines" "FAIL " "$doctor_out"
assert_contains "doctor checks public HTTPS in external mode" "public HTTPS" "$doctor_out"
update_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" ./lumirss update 2>&1)"
rc=$?
assert_eq "update completes against stub docker" "0" "$rc"
assert_contains "update reports completion" "update complete" "$update_out"

echo "== 8. ambiguous pull output must not silently rebuild images =="
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# stub docker that logs invocations; compose pull output is ambiguous
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  inspect) exit 0;;   # images exist locally
  ps) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      pull) echo "Image lumirss-web:latest Skipped"; exit 0;;  # no " Pulled"
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
rebuild_log="$(mktemp)"
update2_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$rebuild_log" ./lumirss update 2>&1)"
assert_contains "ambiguous pull falls back to existing local images" \
  "using existing local images" "$update2_out"
assert_not_contains "ambiguous pull does not trigger a rebuild" \
  "building locally instead" "$update2_out"
if grep -qE "^docker compose build" "$rebuild_log"; then
  bad "stub log shows a compose build ran"
else
  ok "no compose build was invoked"
fi
rm -rf "$sb" "$stub_dir" "$rebuild_log"

# ---------------------------------------------------------------------------
echo "== 9. freshrss-init lifecycle (stub execs) =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# stub docker: execs succeed with empty output (FreshRSS CLI)
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
init_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" ./lumirss freshrss-init 2>&1)"
rc=$?
assert_eq "freshrss-init exits 0" "0" "$rc"
assert_contains "freshrss-init installs FreshRSS" "installing FreshRSS" "$init_out"
assert_contains "freshrss-init generates the API password" "generated FRESHRSS_API_PASSWORD" "$init_out"
assert_contains "freshrss-init creates the BFF user" "creating FreshRSS user" "$init_out"
assert_contains "freshrss-init reports readiness" "FreshRSS ready" "$init_out"
assert_not_contains "freshrss-init never prints the generated password" \
  "$(grep '^FRESHRSS_API_PASSWORD=' "$sb/.env.prod" | cut -d= -f2-)" "$init_out"
pw_val="$(grep '^FRESHRSS_API_PASSWORD=' "$sb/.env.prod" | cut -d= -f2-)"
assert_eq "freshrss-init persists a usable FRESHRSS_API_PASSWORD" "32" "${#pw_val}"
init2_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" ./lumirss freshrss-init 2>&1)"
assert_not_contains "second freshrss-init is idempotent (no regen)" \
  "generated FRESHRSS_API_PASSWORD" "$init2_out"
rm -rf "$sb" "$stub_dir"

# ---------------------------------------------------------------------------
echo
echo "deploy-lifecycle tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
exit 0
