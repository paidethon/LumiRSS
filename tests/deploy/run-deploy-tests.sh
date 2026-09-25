#!/usr/bin/env bash
# Deploy-lifecycle tests (no cluster required):
#   - compose renders for full-stack AND external host-Caddy mode
#   - external mode binds loopback-only and publishes nothing else
#   - web entrypoint renders the site address per mode (":80" vs DOMAIN),
#     inside the real caddy:2-alpine image with a stub `caddy`
#   - preflight port-conflict + caddy-config snippet + configure idempotency
#   - doctor / update run to completion against a stub docker CLI
#   - prebuilt-only: pull failure aborts with the old stack preserved,
#     `--build` refuses the prod compose path
#   - data-preserving upgrade structure: backup → pull → up → health,
#     same volume paths, no `down`, seeded data untouched
#   - export-images / import-images command construction + checksum gate
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
echo "== 10. session auth mode: entrypoint + deploy persistence =="
sb="$(new_sandbox)"
# entrypoint: session mode must pick the NOAUTH template even when stale
# basic-auth values are still present in .env.prod.
stub_dir="$(mktemp -d)"
cat > "$stub_dir/caddy" <<'STUB'
#!/bin/sh
[ "$1" = "run" ] && exec cat "$3"
exit 0
STUB
chmod +x "$stub_dir/caddy"
if docker image inspect caddy:2-alpine >/dev/null 2>&1; then
  etc="$(mktemp -d)"
  out="$(docker run --rm \
    -v "$sb/web":/web:ro \
    -v "$sb/web/Caddyfile.auth":/etc/caddy/Caddyfile.auth:ro \
    -v "$sb/web/Caddyfile.noauth":/etc/caddy/Caddyfile.noauth:ro \
    -v "$etc":/etc/caddy -v "$stub_dir":/stub:ro \
    -e PATH="/stub:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    -e LUMIRSS_AUTH_MODE=session -e LUMIRSS_AUTH_USER=stale -e 'LUMIRSS_AUTH_HASH=$$2b$$12$$x' \
    --entrypoint /bin/sh caddy:2-alpine /web/docker-entrypoint.sh 2>/dev/null)"
  assert_not_contains "entrypoint: session mode drops basic_auth" "basic_auth" "$out"
  assert_contains "entrypoint: session mode keeps internal token / api proxying" "/api/*" "$out"
  rm -rf "$etc"
fi
session_out="$(cd "$sb" && env LUMIRSS_DOMAIN=reader.example.com \
  ./lumirss deploy --auth-mode=session --dry-run 2>&1)"
rc=$?
assert_eq "dry-run session deploy succeeds" "0" "$rc"
assert_contains ".env.prod persisted session mode" "LUMIRSS_AUTH_MODE=session" "$(cat "$sb/.env.prod")"
assert_contains ".env.prod persisted secure cookies" "LUMIRSS_SESSION_SECURE_COOKIES=1" "$(cat "$sb/.env.prod")"
assert_contains "dry-run tells the operator to set a password" "set-password" "$session_out"
rm -rf "$sb" "$stub_dir"

# ---------------------------------------------------------------------------
echo "== 11. low-memory preset writes a complete, consistent budget =="
sb="$(new_sandbox)"
lm_out="$(cd "$sb" && env LUMIRSS_DOMAIN=reader.example.com \
  ./lumirss deploy --low-memory --dry-run 2>&1)"
rc=$?
assert_eq "dry-run low-memory deploy succeeds" "0" "$rc"
for key in LUMIRSS_WEB_MEM_LIMIT LUMIRSS_BFF_MEM_LIMIT LUMIRSS_FRESHRSS_MEM_LIMIT \
           LUMIRSS_RSSHUB_MEM_LIMIT LUMIRSS_RSSHUB_MEMORY_MAX LUMIRSS_RSSHUB_NODE_OPTIONS; do
  val="$(cd "$sb" && grep "^$key=" .env.prod | cut -d= -f2-)"
  if [[ -n "$val" ]]; then ok "preset sets $key"; else bad "preset missing $key"; fi
done
rsshub_limit="$(cd "$sb" && grep '^LUMIRSS_RSSHUB_MEM_LIMIT=' .env.prod | cut -d= -f2-)"
rsshub_heap="$(cd "$sb" && grep '^LUMIRSS_RSSHUB_NODE_OPTIONS=' .env.prod | cut -d= -f2-)"
assert_contains "preset caps the V8 heap" "max-old-space-size=256" "$rsshub_heap"
assert_contains "rsshub container limit (448m) stays above the V8 heap cap" "448m" "$rsshub_limit"
if docker compose version >/dev/null 2>&1; then
  (cd "$sb" && LUMIRSS_EXTERNAL_CADDY=1 docker compose \
     -f docker-compose.prod.yml -f docker-compose.external-caddy.yml config >/dev/null 2>&1)
  assert_eq "low-memory .env.prod renders a valid compose config" "0" "$?"
fi
rm -rf "$sb"

# ---------------------------------------------------------------------------
echo "== 12. set-password: runtime secret only, compose-run one-shot =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
sp_log="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      run) cat >/dev/null; exit 0;;   # consume piped stdin like compose run -T
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
cd "$sb" && cp -f .env.prod.example .env.prod
# dynamic fake credential (convention: no credential-shaped literals)
sp_pw="pw-$(head -c 9 /dev/urandom | base64 | tr -d '=+/')"
sp_out="$(printf '%s' "$sp_pw" | env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$sp_log" \
  ./lumirss set-password 2>&1)"
assert_contains "set-password runs the one-shot container script" \
  "scripts/set_password.py" "$(cat "$sp_log")"
assert_not_contains "set-password log never shows the plaintext" \
  "$sp_pw" "$(cat "$sp_log")"
assert_not_contains "set-password output never shows the plaintext" \
  "$sp_pw" "$sp_out"
assert_contains "set-password reports hash-only persistence" \
  "plaintext not stored" "$sp_out"
no_pw="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$sp_log" ./lumirss set-password </dev/null 2>&1)"
rc=$?
assert_eq "set-password refuses to run without a password source" "1" "$rc"
assert_contains "refusal explains the sources" "LUMIRSS_NEW_PASSWORD" "$no_pw"
cd - >/dev/null
rm -rf "$sb" "$stub_dir" "$sp_log"

# ---------------------------------------------------------------------------
echo "== 13. prebuilt-only: pull failure aborts update, old stack preserved =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
pullfail_log="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# stub docker: registry unreachable (compose pull fails) and the pinned
# images are NOT present locally — the worst-case production pull failure
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  image) exit 1;;     # `docker image inspect`: no local images for this tag
  ps) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      pull) echo 'Error response from daemon: Get "https://ghcr.io/v2/": dial tcp: connection refused' >&2; exit 1;;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
pf_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$pullfail_log" ./lumirss update 2>&1)"
rc=$?
assert_eq "pull failure aborts the update (non-zero exit)" "1" "$rc"
assert_contains "abort names the cause and keeps the old stack" "still running and untouched" "$pf_out"
assert_contains "abort points at the offline import path" "import-images" "$pf_out"
if grep -qE "docker compose .*build" "$pullfail_log"; then
  bad "pull failure triggered a local build"
else
  ok "pull failure did not invoke any build"
fi
if grep -qE "docker compose .*up" "$pullfail_log"; then
  bad "pull failure still ran compose up"
else
  ok "no compose up after pull failure (old stack untouched)"
fi
rm -rf "$sb" "$stub_dir" "$pullfail_log"

# ---------------------------------------------------------------------------
echo "== 14. --build is refused on every production compose path =="
sb="$(new_sandbox)"
bb_out="$(cd "$sb" && env LUMIRSS_ENV=production ./lumirss deploy --build 2>&1)"
rc=$?
assert_eq "deploy --build refuses under LUMIRSS_ENV=production" "1" "$rc"
assert_contains "refusal explains prebuilt-only policy" "prebuilt-only" "$bb_out"
assert_contains "refusal points at the dev/CI build overlay" "docker-compose.build.yml" "$bb_out"
bb2_out="$(cd "$sb" && ./lumirss update --build 2>&1)"
rc=$?
assert_eq "update --build refuses against the prod compose file" "1" "$rc"
assert_contains "refusal also names the overlay on the update path" "docker-compose.build.yml" "$bb2_out"
rm -rf "$sb"

# ---------------------------------------------------------------------------
echo "== 15. data-preserving upgrade: backup → pull → up → health, volumes untouched =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
up_log="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# stub docker: healthy registry + running stack; every call is logged
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  inspect) exit 0;;
  ps) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      pull) echo " Pulled";;
      exec) exit 0;;   # wait_health probe
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
# Seed an existing deployment: a .env.prod and a fake user DB the way a
# long-running host would have one. With a stubbed daemon the volumes are
# structural, so the assertions check the upgrade's shape: the backup step
# mounts the SAME named volumes read-only, nothing ever runs `down`, and
# the seeded data file survives byte-identical.
mkdir -p "$sb/data"
printf 'seeded-user-db-%s\n' "$(date +%s%N)" > "$sb/data/lumi.sqlite"
seed_hash="$(sha256sum "$sb/data/lumi.sqlite" | cut -d' ' -f1)"
upd_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && printf 'DOMAIN=reader.example.com\nLUMIRSS_EXTERNAL_CADDY=1\nLUMIRSS_UPSTREAM_PORT=18080\n' >> .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$up_log" \
     LUMIRSS_BACKUP_DIR="$sb/backups" LUMIRSS_IMAGE_TAG=deadbeefcafe \
     ./lumirss update 2>&1)"
rc=$?
assert_eq "update completes against the stub" "0" "$rc"
assert_contains "update reports completion" "update complete" "$upd_out"
assert_contains "backup mounted the lumi-data volume read-only" \
  "lumirss-prod_lumi-data:/src:ro" "$(cat "$up_log")"
assert_contains "backup mounted the freshrss-data volume read-only" \
  "lumirss-prod_freshrss-data:/src:ro" "$(cat "$up_log")"
[[ -s "$sb/backups/LATEST" ]] && ok "backup step ran (backups/LATEST written)" \
  || bad "backup step did not run"
if grep -qE "docker compose .*down" "$up_log"; then
  bad "update path invoked compose down (data loss risk)"
else
  ok "update never invoked compose down (no -v destruction possible)"
fi
up_line="$(grep -nE "docker compose .* up " "$up_log" | head -1 | cut -d: -f1)"
exec_line="$(grep -nE "docker compose .* exec " "$up_log" | head -1 | cut -d: -f1)"
if [[ -n "$up_line" && -n "$exec_line" && "$exec_line" -gt "$up_line" ]]; then
  ok "post-up health check ran (exec bff after up -d)"
else
  bad "health check missing or ran before up (up=$up_line exec=$exec_line)"
fi
assert_eq "seeded user DB survived the upgrade byte-identical" "$seed_hash" \
  "$(sha256sum "$sb/data/lumi.sqlite" | cut -d' ' -f1)"
rm -rf "$sb" "$stub_dir" "$up_log"

# ---------------------------------------------------------------------------
echo "== 16. export-images / import-images: construction + checksum gate =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
ex_log="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  save)  # honour -o so sha256sum has a real file to hash
    out=""; prev=""
    for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
    [ -n "$out" ] && printf 'fake-image-tar\n' > "$out"
    exit 0;;
  load) exit 0;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
printf '{"schema": "lumirss-release-manifest/v1"}\n' > "$sb/release-manifest.json"
ex_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$ex_log" \
  LUMIRSS_IMAGE_TAG=abc123def456 ./lumirss export-images --out "$sb/offline" 2>&1)"
rc=$?
assert_eq "export-images exits 0" "0" "$rc"
assert_contains "export saves BOTH pinned images in one tar" \
  "save -o $sb/offline/lumirss-images-abc123def456.tar ghcr.io/paidethon/lumirss-web:abc123def456 ghcr.io/paidethon/lumirss-bff:abc123def456" \
  "$(cat "$ex_log")"
[[ -s "$sb/offline/lumirss-images-abc123def456.tar" ]] \
  && ok "export wrote the image tar" || bad "export tar missing"
[[ "$(wc -l < "$sb/offline/SHA256SUMS")" -eq 2 ]] \
  && ok "SHA256SUMS covers tar + release-manifest.json" || bad "SHA256SUMS incomplete"
[[ -f "$sb/offline/release-manifest.json" ]] \
  && ok "export copied release-manifest.json" || bad "release-manifest.json not copied"
im_log="$(mktemp)"
im_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$im_log" \
  ./lumirss import-images "$sb/offline" 2>&1)"
rc=$?
assert_eq "import-images exits 0" "0" "$rc"
assert_contains "import verifies checksums before load" "verifying SHA256SUMS" "$im_out"
assert_contains "import loads the exported tar" \
  "load -i $sb/offline/lumirss-images-abc123def456.tar" "$(cat "$im_log")"
printf 'corrupted\n' > "$sb/offline/lumirss-images-abc123def456.tar"
bad_log="$(mktemp)"
bad_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$bad_log" \
  ./lumirss import-images "$sb/offline" 2>&1)"
rc=$?
assert_eq "import refuses a corrupted bundle" "1" "$rc"
assert_contains "refusal names the checksum failure" "checksum verification failed" "$bad_out"
if grep -q "docker load" "$bad_log"; then
  bad "corrupted bundle still reached docker load"
else
  ok "corrupted bundle never reached docker load"
fi
rm -rf "$sb" "$stub_dir" "$ex_log" "$im_log" "$bad_log"

# ---------------------------------------------------------------------------
echo "== 14. update writes stage progress JSON (N196, stub docker) =="
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
      exec) exit 0;;   # wait_health probe inside the bff container
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
status_dir="$(mktemp -d)"
status_file="$status_dir/deploy-status.json"
update_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_DEPLOY_STATUS_FILE="$status_file" \
     LUMIRSS_IMAGE_TAG=abcdef123456 ./lumirss update 2>&1)"
rc=$?
assert_eq "update with status reporting completes" "0" "$rc"
[[ -s "$status_file" ]] && ok "status file written" || bad "status file missing"
assert_contains "status JSON has every stage ok + result success + tag" "STATUS-JSON-OK" "$(python3 - "$status_file" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    print("STATUS-JSON-BAD"); raise SystemExit
stages = data.get("stages", {})
ok = data.get("schema") == "lumirss-deploy-status/v1"
for name in ("backup", "pull", "migrate", "health"):
    ok = ok and stages.get(name, {}).get("status") == "ok"
    ok = ok and bool(stages.get(name, {}).get("startedAt")) and bool(stages.get(name, {}).get("finishedAt"))
ok = ok and data.get("result", {}).get("status") == "success" and data.get("imageTag") == "abcdef123456"
print("STATUS-JSON-OK" if ok else "STATUS-JSON-BAD")
PY
)"
assert_not_contains "status file carries no secrets" "LUMIRSS_INTERNAL_TOKEN" "$(cat "$status_file")"

# Failed pull → honest failed stages + failed result, exit nonzero.
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  image)  # `docker image inspect` fails: no local images either
    sub="$1"; shift
    case "$sub" in inspect) exit 1;; *) exit 0;; esac;;
  ps) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      pull) echo "Image Skipped";;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
fail_dir="$(mktemp -d)"
fail_file="$fail_dir/deploy-status-failed.json"
fail_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_DEPLOY_STATUS_FILE="$fail_file" \
  ./lumirss update 2>&1)"
rc=$?
assert_eq "failed pull exits 1" "1" "$rc"
assert_contains "failed update records pull failed + result failed" "failed failed" \
  "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["stages"]["pull"]["status"], d["result"]["status"])' "$fail_file" 2>/dev/null || echo broken)"
rm -rf "$sb" "$stub_dir" "$status_dir" "$fail_dir"

# ---------------------------------------------------------------------------
echo
echo "deploy-lifecycle tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
exit 0
