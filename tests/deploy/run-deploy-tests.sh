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
# stub docker: everything succeeds, compose subcommands answer sanely.
# inspect answers per --format so FIX-207's per-service probes behave;
# exec answers the version endpoint (FIX-199 verify) and inspect/image
# agree on one image ID so the digest-parity gate passes.
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  image)
    case "$*" in
      *inspect*) echo "sha256:stub-image-id";;
      *) exit 0;;
    esac;;
  inspect)
    case "$*" in
      *"{{.Image}}"*) echo "sha256:stub-image-id";;
      *OOMKilled*) echo false;;
      *RestartCount*) echo 0;;
      *"State.Health"*) echo none;;
      *) echo running;;
    esac;;
  ps) exit 0;;
  compose)
    # COMPOSE_ARGS precede the subcommand, so match on the whole arg string
    # (a sub="$1" case would never match: the first arg is "-f").
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod", "services": {"web": {}, "bff": {}, "freshrss": {}, "rsshub": {}}}';;
      *" pull"*) echo " Pulled";;
      *" exec"*) echo '{"commit": "stub-commit", "version": "2.0.1"}';;
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
  image) echo "sha256:stub-image-id";;   # images exist locally
  inspect)
    case "$*" in
      *"{{.Image}}"*) echo "sha256:stub-image-id";;
      *) exit 0;;
    esac;;
  ps) exit 0;;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *" pull"*) echo "Image lumirss-web:latest Skipped"; exit 0;;  # no " Pulled"
      *" exec"*) echo '{"commit": "stub-commit", "version": "2.0.1"}';;
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
init_log="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# stub docker: execs succeed with empty output (FreshRSS CLI); every call
# is logged so FIX-210 can assert what reaches process argv.
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
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
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$init_log" ./lumirss freshrss-init 2>&1)"
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
# FIX-210: the ONLY password argument reaching process argv is the greader
# API password FreshRSS 1.29.1 cannot consume any other way; the unused
# web-login --password is gone (upstream constraint documented in lumirss).
assert_contains "create-user receives the api password" "--api-password" "$(cat "$init_log")"
assert_not_contains "unused web-login --password argv is gone" " --password " "$(cat "$init_log")"
assert_eq "plaintext reaches argv exactly once (single copy; upstream-forced channel)" "1" \
  "$(grep -o -F -- "$pw_val" "$init_log" | wc -l)"
init2_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$init_log" ./lumirss freshrss-init 2>&1)"
assert_not_contains "second freshrss-init is idempotent (no regen)" \
  "generated FRESHRSS_API_PASSWORD" "$init2_out"
rm -rf "$sb" "$stub_dir" "$init_log"

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
  inspect)
    case "$*" in
      *"{{.Image}}"*) echo "sha256:stub-image-id";;
      *) exit 0;;
    esac;;
  image) echo "sha256:stub-image-id";;
  ps) exit 0;;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *" pull"*) echo " Pulled";;
      *" exec"*) echo '{"commit": "stub-commit", "version": "2.0.1"}';;   # wait_health probe + version verify
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
# FIX-192: the snapshot pass mounts BOTH live volumes READ-ONLY (structural
# shape under a stubbed daemon; real execution is proven in section 17).
assert_contains "backup mounted the lumi-data volume read-only" \
  "lumirss-prod_lumi-data:/src/lumi-data:ro" "$(cat "$up_log")"
assert_contains "backup mounted the freshrss-data volume read-only" \
  "lumirss-prod_freshrss-data:/src/freshrss-data:ro" "$(cat "$up_log")"
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
echo "== 16. export-images / import-images: construction + checksum gate + full pinned set (FIX-205) =="
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
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod", "services": {"freshrss": {"image": "freshrss/freshrss:1.29.1@sha256:ab6b363102ccdbc39f6a62db926f567c61a5289bf25ba460f1c34423d8cc1a4d"}, "rsshub": {"image": "diygod/rsshub@sha256:387fd32ee2d8789154dcf6446a52365976e768d9ede1a7c1e610cf4da9d89fbc"}}}';;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
printf '{"schema": "lumirss-release-manifest/v1"}\n' > "$sb/release-manifest.json"
ex_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$ex_log" \
  LUMIRSS_IMAGE_TAG=abc123def456 ./lumirss export-images --out "$sb/offline" 2>&1)"
rc=$?
assert_eq "export-images exits 0" "0" "$rc"
# D-01: image references must match docker-compose.prod.yml (the registry
# path gained the repository segment; the old ghcr.io/paidethon/lumirss-web
# names no longer exist and broke the offline release chain).
assert_contains "export saves BOTH pinned images in one tar (current registry path)" \
  "save -o $sb/offline/lumirss-images-abc123def456.tar ghcr.io/paidethon/lumirss/lumirss-web:abc123def456 ghcr.io/paidethon/lumirss/lumirss-bff:abc123def456" \
  "$(cat "$ex_log")"
# FIX-205: a complete offline install set must also carry the digest-pinned
# freshrss/rsshub images (resolved from compose, the single source of pins).
assert_contains "export includes the digest-pinned freshrss image" \
  "freshrss/freshrss:1.29.1@sha256:ab6b363102ccdbc39f6a62db926f567c61a5289bf25ba460f1c34423d8cc1a4d" "$(cat "$ex_log")"
assert_contains "export includes the digest-pinned rsshub image" \
  "diygod/rsshub@sha256:387fd32ee2d8789154dcf6446a52365976e768d9ede1a7c1e610cf4da9d89fbc" "$(cat "$ex_log")"
assert_not_contains "export never references the retired registry path" \
  "ghcr.io/paidethon/lumirss-web" "$(cat "$ex_log")"
assert_not_contains "export never references the retired bff path" \
  "ghcr.io/paidethon/lumirss-bff" "$(cat "$ex_log")"
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
# FIX-205 degraded path: compose unanswerable → honest warning, web+bff
# still exported (bundle explicitly flagged as NOT the complete install set).
: > "$ex_log"
minimal_stub="$(mktemp -d)"
cat > "$minimal_stub/docker" <<'STUB'
#!/bin/sh
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  save)
    out=""; prev=""
    for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
    [ -n "$out" ] && printf 'fake-image-tar\n' > "$out"
    exit 0;;
  *) exit 0;;
esac
STUB
chmod +x "$minimal_stub/docker"
dg_out="$(cd "$sb" && env PATH="$minimal_stub:$PATH" LUMIRSS_TEST_DOCKER_LOG="$ex_log" \
  LUMIRSS_IMAGE_TAG=abc123def456 ./lumirss export-images --out "$sb/offline2" 2>&1)"
assert_contains "degraded export warns the bundle is incomplete" \
  "NOT a complete offline install set" "$dg_out"
assert_contains "degraded export still saves web+bff" \
  "save -o $sb/offline2/lumirss-images-abc123def456.tar ghcr.io/paidethon/lumirss/lumirss-web:abc123def456 ghcr.io/paidethon/lumirss/lumirss-bff:abc123def456" \
  "$(cat "$ex_log")"
rm -rf "$minimal_stub"
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
  image) echo "sha256:stub-image-id";;
  inspect)
    case "$*" in
      *"{{.Image}}"*) echo "sha256:stub-image-id";;
      *) echo healthy;;
    esac;;
  ps) exit 0;;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *" pull"*) echo " Pulled";;
      *" exec"*) echo '{"commit": "stub-commit", "version": "2.0.1"}';;
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
echo "== 18. FIX-201: backup failure aborts update BEFORE pull/switch/migration =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
fail_log="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# stub docker: every backup container fails; pull/up would succeed if reached
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) echo "simulated backup failure" >&2; exit 1;;
  ps) exit 0;;
  compose)
    sub="$1"; shift
    case "$sub" in
      version) exit 0;;
      config) echo '{"name": "lumirss-prod"}';;
      pull) echo " Pulled";;
      exec) exit 0;;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
status_dir="$(mktemp -d)"
status_file="$status_dir/backup-fail-status.json"
ab_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$fail_log" \
     LUMIRSS_DEPLOY_STATUS_FILE="$status_file" ./lumirss update 2>&1)"
rc=$?
assert_eq "backup failure aborts the update (non-zero exit)" "1" "$rc"
assert_contains "abort names the backup as the cause" "update aborted" "$ab_out"
assert_contains "abort states the old services keep running" "old services keep running" "$ab_out"
assert_contains "deploy status records backup failed + result failed" "failed failed" \
  "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["stages"]["backup"]["status"], d["result"]["status"])' "$status_file" 2>/dev/null || echo broken)"
if grep -qE "docker compose .*(pull|up)" "$fail_log"; then
  bad "update proceeded to pull/up after the backup failure"
else
  ok "no pull/up after backup failure (old stack untouched, no migration)"
fi
rm -rf "$sb" "$stub_dir" "$fail_log" "$status_dir"

# ---------------------------------------------------------------------------
echo "== 17. FIX-192: consistent backup under a concurrent writer + isolated recovery (real docker) =="
if docker info >/dev/null 2>&1; then
  sb="$(new_sandbox)"
  cp "$REPO_ROOT/VERSION" "$sb/VERSION"
  stub_dir="$(mktemp -d)"
  live_log="$(mktemp)"
  real_docker="$(command -v docker)"
  vol="$sb/volumes"
  mkdir -p "$vol/lumi-data/users/u_fix192" "$vol/freshrss-data"
  printf 'control-secret\n' > "$vol/lumi-data/control-secrets.json"
  printf 'user-secret\n' > "$vol/lumi-data/users/u_fix192/secrets.json"
  printf '<?php // freshrss config\n' > "$vol/freshrss-data/config.php"

  # Source DBs carry the BFF's REAL schema (its own migration runner) and run
  # in WAL mode, exactly like the deployed stack (control lumi.sqlite +
  # per-user users/<uid>/lumi.sqlite + FreshRSS db.sqlite).
  seed_out="$(PYTHONPATH="$REPO_ROOT/services/bff/src" python3 - "$vol" <<'PY'
import sqlite3, sys
from pathlib import Path
from lumirss.storage import Database
from lumirss.migrations import apply_migrations, schema_version
vol = Path(sys.argv[1])
ctl = Database(vol / "lumi-data" / "lumi.sqlite")
apply_migrations(ctl)
c = sqlite3.connect(vol / "lumi-data" / "lumi.sqlite")
c.execute("PRAGMA journal_mode=WAL")
c.execute("CREATE TABLE IF NOT EXISTS fix192_probe (id INTEGER PRIMARY KEY, payload TEXT)")
c.executemany("INSERT INTO fix192_probe(payload) VALUES (?)", [("seed-%d" % i,) for i in range(5)])
c.commit(); c.close()
u = Database(vol / "lumi-data" / "users" / "u_fix192" / "lumi.sqlite")
apply_migrations(u)
f = sqlite3.connect(vol / "freshrss-data" / "db.sqlite")
f.execute("PRAGMA journal_mode=WAL")
f.execute("CREATE TABLE fix192_frs (id INTEGER PRIMARY KEY, v TEXT)")
f.executemany("INSERT INTO fix192_frs(v) VALUES (?)", [("frs-%d" % i,) for i in range(7)])
f.commit(); f.close()
print(schema_version(ctl))
PY
)"
  src_ver="$(printf '%s\n' "$seed_out" | tail -1)"

  # Concurrent writer, like a live BFF: phase 1 commits 120 rows BEFORE the
  # backup starts (every one of them MUST appear in the recovery); phase 2
  # keeps writing while the snapshot runs. wal_autocheckpoint=0 keeps every
  # commit in the -wal, so a bare tar of the main file would lose rows —
  # only the online backup API reads through WAL.
  cat > "$sb/writer.py" <<'PY'
import sqlite3, sys, time
db = sqlite3.connect(sys.argv[1], timeout=30.0)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA wal_autocheckpoint=0")
for i in range(120):
    db.execute("INSERT INTO fix192_probe(payload) VALUES (?)", ("writer-%d" % i,))
    db.commit()
open(sys.argv[2], "w").write("phase1")
for i in range(120, 400):
    db.execute("INSERT INTO fix192_probe(payload) VALUES (?)", ("writer-%d" % i,))
    db.commit()
    time.sleep(0.01)
open(sys.argv[2], "w").write("done")
time.sleep(180)   # stay alive: hold -wal/-shm open like a running BFF
PY
  rm -f "$sb/writer.state"
  python3 "$sb/writer.py" "$vol/lumi-data/lumi.sqlite" "$sb/writer.state" &
  writer_pid=$!
  for _ in $(seq 1 100); do [[ -s "$sb/writer.state" ]] && break; sleep 0.1; done
  if [[ "$(cat "$sb/writer.state" 2>/dev/null || true)" == *phase1* ]]; then
    ok "writer committed 120 rows before the backup started"
  else
    bad "writer did not reach phase 1 (test harness broken)"
  fi

  # Smart stub: only `compose config` is answered (project name + bff image);
  # `docker run` is rewritten from project volumes to test bind dirs and
  # delegated to the REAL docker — the CLI's own snapshot program, mounts,
  # exclusion tars, MANIFEST and restore/overlay/verify logic all execute for
  # real. Harness paths never contain spaces/quotes, so plain token joining
  # is safe; --user keeps container-written files owned by the test user.
  cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run)
    fwd="--user $(id -u):$(id -g)"
    for a in "$@"; do
      case "$a" in
        lumirss-prod_lumi-data:*) a="$LUMITEST_LUMI_VOL${a#lumirss-prod_lumi-data}";;
        lumirss-prod_freshrss-data:*) a="$LUMITEST_FRS_VOL${a#lumirss-prod_freshrss-data}";;
      esac
      fwd="$fwd '$a'"
    done
    eval "exec '$LUMITEST_REAL_DOCKER' run $fwd"
    ;;
  ps) exit 0;;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod", "services": {"bff": {"image": "python:3.12-slim"}}}';;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
  chmod +x "$stub_dir/docker"

  bk_rc=0
  bk_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
    && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$live_log" \
    LUMIRSS_BACKUP_DIR="$sb/backups" LUMITEST_LUMI_VOL="$vol/lumi-data" \
    LUMITEST_FRS_VOL="$vol/freshrss-data" LUMITEST_REAL_DOCKER="$real_docker" \
    ./lumirss backup 2>&1)" || bk_rc=$?
  for _ in $(seq 1 600); do [[ "$(cat "$sb/writer.state" 2>/dev/null || true)" == *done* ]] && break; sleep 0.1; done
  kill "$writer_pid" 2>/dev/null || true
  wait "$writer_pid" 2>/dev/null || true
  assert_eq "backup with a live concurrent writer exits 0" "0" "$bk_rc"
  assert_contains "snapshot pass ran the online backup API" "online backup API" "$bk_out"
  stamp_dir="$sb/backups/$(cat "$sb/backups/LATEST" 2>/dev/null || echo MISSING)"
  for artifact in MANIFEST.txt lumi-sqlite lumi-data.files.tar.gz freshrss-data.files.tar.gz config.tar.gz; do
    [[ -e "$stamp_dir/$artifact" ]] && ok "backup contains $artifact" || bad "backup missing $artifact"
  done
  manifest="$(cat "$stamp_dir/MANIFEST.txt" 2>/dev/null || true)"
  assert_contains "manifest records the CLI version" "cli_version: 2.0.1" "$manifest"
  assert_contains "manifest lists the control DB" "lumi-sqlite/lumi.sqlite" "$manifest"
  assert_contains "manifest lists the per-user DB" "lumi-sqlite/users/u_fix192/lumi.sqlite" "$manifest"
  assert_contains "manifest lists the FreshRSS DB" "freshrss-sqlite/db.sqlite" "$manifest"
  if tar -tzf "$stamp_dir/lumi-data.files.tar.gz" > "$sb/lumi-tar.list" 2>/dev/null && [[ -s "$sb/lumi-tar.list" ]]; then
    if grep -q "sqlite" "$sb/lumi-tar.list"; then
      bad "file-level tar still contains a live SQLite file (bare-tar regression)"
    else
      ok "file-level tar excludes every SQLite DB and sidecar"
    fi
    assert_contains "file-level tar keeps non-DB state (secrets.json)" \
      "secrets.json" "$(cat "$sb/lumi-tar.list")"
  else
    bad "lumi-data.files.tar.gz missing or unreadable"
    bad "file-level tar keeps non-DB state (secrets.json) — tar missing"
  fi

  # Isolated application recovery: restore BOTH volumes into a scratch
  # layout through the CLI itself (untar + snapshot overlay + MANIFEST
  # checksum verification run for real inside containers).
  mkdir -p "$sb/restored/lumi-data" "$sb/restored/freshrss-data"
  rs_rc=0
  rs_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$live_log" \
    LUMIRSS_BACKUP_DIR="$sb/backups" LUMITEST_LUMI_VOL="$sb/restored/lumi-data" \
    LUMITEST_FRS_VOL="$sb/restored/freshrss-data" LUMITEST_REAL_DOCKER="$real_docker" \
    ./lumirss restore "$stamp_dir/lumi-data.files.tar.gz" --yes 2>&1)" || rs_rc=$?
  assert_eq "lumi restore (untar + overlay + MANIFEST verify) exits 0" "0" "$rs_rc"
  assert_contains "restore verified the manifest checksums" "verifying MANIFEST.txt checksums" "$rs_out"
  rs2_rc=0
  (cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$live_log" \
    LUMIRSS_BACKUP_DIR="$sb/backups" LUMITEST_LUMI_VOL="$sb/restored/lumi-data" \
    LUMITEST_FRS_VOL="$sb/restored/freshrss-data" LUMITEST_REAL_DOCKER="$real_docker" \
    ./lumirss restore "$stamp_dir/freshrss-data.files.tar.gz" --yes >/dev/null 2>&1) || rs2_rc=$?
  assert_eq "freshrss restore exits 0" "0" "$rs2_rc"

  # Verify the recovered DBs with the BFF's OWN logic — not just
  # integrity_check: apply its migration runner, compare schema versions,
  # and prove the recovered rows are a tear-free prefix of the writer's
  # commit stream (all 125 pre-backup commits present, no gaps, no torn
  # payloads; rows committed during the snapshot may legitimately be absent).
  rec_out="$(PYTHONPATH="$REPO_ROOT/services/bff/src" python3 - "$sb" "$src_ver" <<'PY'
import sqlite3, sys
from pathlib import Path
from lumirss.storage import Database
from lumirss.migrations import apply_migrations, schema_version
sb = Path(sys.argv[1]); src_ver = int(sys.argv[2])
ctl_path = sb / "restored" / "lumi-data" / "lumi.sqlite"
db = Database(ctl_path)
applied = apply_migrations(db)
ver = schema_version(db)
c = sqlite3.connect(ctl_path)
integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
ids = [r[0] for r in c.execute("SELECT id FROM fix192_probe ORDER BY id")]
n = len(ids)
contiguous = ids == list(range(1, n + 1))
seeds = c.execute("SELECT COUNT(*) FROM fix192_probe WHERE payload LIKE 'seed-%'").fetchone()[0]
payload_ok = c.execute(
    "SELECT COUNT(*) FROM fix192_probe WHERE id > 5 AND payload = 'writer-' || (id - 6)"
).fetchone()[0]
uver = schema_version(Database(sb / "restored" / "lumi-data" / "users" / "u_fix192" / "lumi.sqlite"))
uinteg = sqlite3.connect(
    sb / "restored" / "lumi-data" / "users" / "u_fix192" / "lumi.sqlite"
).execute("PRAGMA integrity_check").fetchone()[0]
frs = sqlite3.connect(sb / "restored" / "freshrss-data" / "db.sqlite")
finteg = frs.execute("PRAGMA integrity_check").fetchone()[0]
frows = frs.execute("SELECT COUNT(*) FROM fix192_frs").fetchone()[0]
good = (ver == src_ver and not applied and integrity == "ok" and contiguous and n >= 125
        and seeds == 5 and payload_ok == n - 5 and uver == src_ver and uinteg == "ok"
        and finteg == "ok" and frows == 7)
print("%s recovered_rows=%d schema=%d integrity=%s" % (
    "RECOVERY-OK" if good else "RECOVERY-BAD", n, ver, integrity))
PY
)"
  assert_contains "recovered DBs pass the BFF's own migration + integrity + prefix checks" "RECOVERY-OK" "$rec_out"
  recovered_rows="$(printf '%s' "$rec_out" | sed -n 's/.*recovered_rows=\([0-9]*\).*/\1/p')"
  if [[ -n "$recovered_rows" && "$recovered_rows" -ge 125 ]]; then
    ok "all pre-backup commits recovered ($recovered_rows rows, WAL-only rows included)"
  else
    bad "pre-backup commits missing from the recovered DB ($rec_out)"
  fi
  rm -rf "$sb" "$stub_dir" "$live_log"
else
  bad "docker daemon unavailable — FIX-192 concurrency/recovery tests NOT executed"
fi

echo "== 19. FIX-209: unique backup dirs on rapid runs; LATEST atomic + success-only =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  ps) exit 0;;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
(cd "$sb" && cp -f .env.prod.example .env.prod)
(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_BACKUP_DIR="$sb/backups" ./lumirss backup >/dev/null 2>&1)
assert_eq "first rapid backup succeeds" "0" "$?"
before="$(ls "$sb/backups" | grep -v '^LATEST$')"
(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_BACKUP_DIR="$sb/backups" ./lumirss backup >/dev/null 2>&1)
assert_eq "second rapid backup (same second) succeeds" "0" "$?"
after="$(ls "$sb/backups" | grep -v '^LATEST$')"
new_dir="$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | head -1)"
assert_eq "rapid consecutive backups land in UNIQUE directories (2 runs → 2 dirs)" "2" \
  "$(printf '%s\n' "$after" | wc -l)"
assert_eq "LATEST points at the newest backup dir" "$new_dir" "$(cat "$sb/backups/LATEST")"
assert_contains "both backups survive (no clobbering)" "$before" "$(printf '%s\n' "$after")"

# A failed backup must not touch LATEST or any prior backup.
fail_stub="$(mktemp -d)"
cat > "$fail_stub/docker" <<'STUB'
#!/bin/sh
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 1;;          # backup containers fail
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$fail_stub/docker"
printf '20200101-000000\n' > "$sb/backups/LATEST"
mkdir -p "$sb/backups/20200101-000000"
printf 'prior-backup-canary\n' > "$sb/backups/20200101-000000/keep.txt"
count_before="$(ls -A "$sb/backups" | wc -l)"
(cd "$sb" && env PATH="$fail_stub:$PATH" LUMIRSS_BACKUP_DIR="$sb/backups" ./lumirss backup >/dev/null 2>&1)
assert_eq "failing backup exits non-zero" "1" "$?"
assert_eq "existing LATEST preserved on failure" "20200101-000000" "$(cat "$sb/backups/LATEST")"
assert_eq "prior backup content untouched on failure" "prior-backup-canary" \
  "$(cat "$sb/backups/20200101-000000/keep.txt")"
assert_eq "no partial backup dir or LATEST temp left behind" "$count_before" \
  "$(ls -A "$sb/backups" | wc -l)"
rm -rf "$sb" "$stub_dir" "$fail_stub"

# ---------------------------------------------------------------------------
echo "== 20. FIX-203: hostile backup filename must not change the restore command (real docker) =="
if docker info >/dev/null 2>&1; then
  sb="$(new_sandbox)"
  stub_dir="$(mktemp -d)"
  real_docker="$(command -v docker)"
  # Quote-safe forwarder (bash arrays, no eval): rewrites project volume
  # mounts onto harness bind dirs and passes EVERY argv byte-for-byte to the
  # real docker — the hostile filename below contains quotes, so the section
  # 17 eval-joining stub would itself corrupt it (harness artifact, not code).
  cat > "$stub_dir/docker" <<'STUB'
#!/bin/bash
args=("$@")
if [[ "${args[0]}" == "compose" ]]; then
  case "${args[*]}" in
    # bff image answer keeps backup_image() on a locally-present image
    # (python:3.12-slim, as in section 17) instead of the GHCR fallback.
    *" config"*) echo '{"name": "lumirss-prod", "services": {"bff": {"image": "python:3.12-slim"}}}';;
    *) exit 0;;   # stop/start/exec (restore health wait) succeed
  esac
  exit 0
fi
for i in "${!args[@]}"; do
  case "${args[$i]}" in
    lumirss-prod_lumi-data:*) args[$i]="$LUMITEST_LUMI_VOL${args[$i]#lumirss-prod_lumi-data}";;
    lumirss-prod_freshrss-data:*) args[$i]="$LUMITEST_FRS_VOL${args[$i]#lumirss-prod_freshrss-data}";;
  esac
done
exec "$LUMITEST_REAL_DOCKER" "${args[@]}"
STUB
  chmod +x "$stub_dir/docker"

  # Hand-made new-format backup: snapshot tree + MANIFEST.txt + the files tar
  # under a HOSTILE name (space ; closed backticks command-substitution glob
  # single+double quotes &). With the pre-fix string-concatenated
  # `sh -c "tar xzf /bkp/$(basename …)"` the ; quotes and substitutions
  # change the command meaning (tar fails / runs other commands). The
  # parameterized form must extract the exact name with identical content.
  stamp="$sb/bk-stamp"
  mkdir -p "$stamp/lumi-sqlite"
  python3 -c 'import sqlite3
c = sqlite3.connect("'"$stamp"'/lumi-sqlite/lumi.sqlite")
c.execute("CREATE TABLE t (v TEXT)")
c.execute("INSERT INTO t VALUES (?)", ("fix203-snapshot",))
c.commit()'
  printf 'restore-canary\n' > "$stamp/canary.txt"
  evil='lumi-data; sp ace;`id` $(date +%s)*'"'"'q"d&x.tar.gz'
  tar -C "$stamp" -czf "$stamp/$evil" canary.txt
  dig="$(sha256sum "$stamp/lumi-sqlite/lumi.sqlite" | cut -d' ' -f1)"
  size="$(stat -c %s "$stamp/lumi-sqlite/lumi.sqlite")"
  printf '# LumiRSS backup manifest (FIX-192)\n%s  %s  lumi-sqlite/lumi.sqlite\n' "$dig" "$size" > "$stamp/MANIFEST.txt"

  vol="$sb/restore-vol"; mkdir -p "$vol"
  rs_rc=0
  rs_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
    && env PATH="$stub_dir:$PATH" LUMITEST_LUMI_VOL="$vol" \
    LUMITEST_FRS_VOL="$sb/unused-frs" LUMITEST_REAL_DOCKER="$real_docker" \
    ./lumirss restore "$stamp/$evil" --yes 2>&1)" || rs_rc=$?
  assert_eq "restore with hostile filename exits 0" "0" "$rs_rc"
  assert_contains "restore verified the manifest checksums" "verifying MANIFEST.txt checksums" "$rs_out"
  assert_eq "hostile-named tar extracted under its EXACT name (command meaning unchanged)" \
    "restore-canary" "$(cat "$vol/canary.txt" 2>/dev/null || echo MISSING)"
  assert_contains "snapshot overlay applied on top" "fix203-snapshot" \
    "$(python3 -c 'import sqlite3; print(sqlite3.connect("'"$vol"'/lumi.sqlite").execute("SELECT v FROM t").fetchone()[0])' 2>/dev/null || echo BROKEN)"
  if find "$vol" -name 'PWNED' -o -name '*hacked*' 2>/dev/null | grep -q .; then
    bad "injection side effect appeared in the restored volume"
  else
    ok "no injection side effect in the restored volume"
  fi
  rm -rf "$sb" "$stub_dir"
else
  bad "docker daemon unavailable — FIX-203 hostile-filename tests NOT executed"
fi

# ---------------------------------------------------------------------------
echo "== 21. FIX-195: concurrent update is refused fast; crash-leftover lock is takeable =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
lock1_log="$(mktemp)"; lock2_log="$(mktemp)"
lock_mark="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  image) echo "sha256:stub-image-id";;
  inspect)
    case "$*" in
      *"{{.Image}}"*) echo "sha256:stub-image-id";;
      *) echo healthy;;
    esac;;
  ps) exit 0;;
  compose)
    # COMPOSE_ARGS precede the subcommand, so match on the whole arg string.
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod", "services": {"bff": {"image": "python:3.12-slim"}}}';;
      *" pull"*)
        # widen the window: run #1 holds the update lock inside this pull
        [ -n "${LUMIRSS_TEST_LOCK_MARK:-}" ] && printf 'pull-started\n' > "$LUMIRSS_TEST_LOCK_MARK"
        sleep 6
        echo " Pulled";;
      *" exec"*) echo '{"commit": "stub-commit", "version": "2.0.1"}';;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_LOCK_MARK="$lock_mark" \
     LUMIRSS_BACKUP_DIR="$sb/backups1" ./lumirss update > "$lock1_log" 2>&1) &
upd1_pid=$!
for _ in $(seq 1 100); do [[ -s "$lock_mark" ]] && break; sleep 0.1; done
if [[ -s "$lock_mark" ]]; then
  ok "run #1 reached the pull stage (lock held)"
else
  bad "run #1 never reached the pull stage (test harness broken)"
fi
lock2_rc=0
t0="$(date +%s%N)"
(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_BACKUP_DIR="$sb/backups2" \
   ./lumirss update > "$lock2_log" 2>&1) || lock2_rc=$?
t1="$(date +%s%N)"
lock2_ms=$(( (t1 - t0) / 1000000 ))
assert_eq "run #2 refuses while run #1 holds the lock (non-zero exit)" "1" "$lock2_rc"
assert_contains "refusal is explicit about the concurrent holder" "already running" "$(cat "$lock2_log")"
assert_contains "refusal names the lock file" ".update.lock" "$(cat "$lock2_log")"
if [[ "$lock2_ms" -lt 4000 ]]; then
  ok "run #2 failed fast (${lock2_ms} ms, no backup/pull executed)"
else
  bad "run #2 did not fail fast (${lock2_ms} ms)"
fi
if grep -qE "docker compose .*(pull|up)" "$lock2_log"; then
  bad "run #2 got past the lock"
else
  ok "run #2 never reached backup/pull/migration (no compose calls in its log)"
fi
[[ ! -e "$sb/backups2" ]] \
  && ok "run #2 produced no backup (refused before the backup stage)" \
  || bad "run #2 performed work before hitting the lock"
upd1_rc=0
wait "$upd1_pid" 2>/dev/null || upd1_rc=$?
assert_eq "run #1 completes normally after run #2 was refused" "0" "$upd1_rc"
assert_contains "run #1 reports completion" "update complete" "$(cat "$lock1_log")"

# Crash-leftover: the lock FILE may survive a killed run (SIGKILL cannot run
# cleanup), but flock(2) releases with the process — a bare leftover file
# must be takeable, not sticky.
printf '999999\n' > "$sb/.update.lock"
stale_rc=0
(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_BACKUP_DIR="$sb/backups3" \
   ./lumirss update > "$lock1_log" 2>&1) || stale_rc=$?
assert_eq "update succeeds with a leftover lock file from a dead run" "0" "$stale_rc"
rm -rf "$sb" "$stub_dir" "$lock1_log" "$lock2_log" "$lock_mark"

# ---------------------------------------------------------------------------
echo "== 22. FIX-208: each update run gets its own run_id; retries never mix two runs' progress =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  image) echo "sha256:stub-image-id";;
  inspect)
    case "$*" in
      *"{{.Image}}"*) echo "sha256:stub-image-id";;
      *) echo healthy;;
    esac;;
  ps) exit 0;;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *" pull"*) echo " Pulled";;
      *" exec"*) echo '{"commit": "stub-commit", "version": "2.0.1"}';;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
status_dir="$(mktemp -d)"
status_file="$status_dir/retry-status.json"
# Residue of a PREVIOUS failed run: old startedAt, a stale failed stage, a
# ghost stage that never existed in this run, and a failed result.
cat > "$status_file" <<'JSON'
{"command": "update", "imageTag": "oldtag",
 "result": {"finishedAt": "2020-01-01T00:00:01Z", "status": "failed"},
 "runId": "previous-run-20200101",
 "schema": "lumirss-deploy-status/v1",
 "stages": {
   "ghost": {"startedAt": "2020-01-01T00:00:00Z", "status": "running"},
   "health": {"finishedAt": "2020-01-01T00:00:01Z", "startedAt": "2020-01-01T00:00:00Z", "status": "failed"}
 },
 "startedAt": "2020-01-01T00:00:00Z", "updatedAt": "2020-01-01T00:00:01Z"}
JSON
retry_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_DEPLOY_STATUS_FILE="$status_file" \
     LUMIRSS_IMAGE_TAG=retry208tag ./lumirss update 2>&1)"
rc=$?
assert_eq "update over a previous run's failed status file completes" "0" "$rc"
assert_contains "retry assigns a NEW run_id (not the previous run's)" "RUN-ID-OK" \
  "$(python3 - "$status_file" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
rid = d.get("runId", "")
print("RUN-ID-OK" if rid and rid != "previous-run-20200101" else "RUN-ID-BAD")
PY
)"
assert_contains "retry restarts startedAt (does not inherit the failed run's)" "STARTED-AT-OK" \
  "$(python3 - "$status_file" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("STARTED-AT-OK" if d.get("startedAt", "").startswith("20") and not d["startedAt"].startswith("2020-01-01") else "STARTED-AT-BAD")
PY
)"
assert_contains "ghost stage from the previous run is gone" "GHOST-GONE" \
  "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("GHOST-GONE" if "ghost" not in d["stages"] else "GHOST-STILL-THERE")' "$status_file")"
assert_contains "previous failed health stage replaced by this run's ok stage" "HEALTH-OK" \
  "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("HEALTH-OK" if d["stages"].get("health",{}).get("status")=="ok" else "HEALTH-BAD")' "$status_file")"
assert_contains "result reflects only this run" "success" \
  "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["result"]["status"])' "$status_file")"
run1_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("runId"))' "$status_file")"
# A second consecutive run must also get a DIFFERENT run id (per-run identity).
(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_DEPLOY_STATUS_FILE="$status_file" \
   LUMIRSS_IMAGE_TAG=retry208tag ./lumirss update >/dev/null 2>&1)
run2_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("runId"))' "$status_file")"
if [[ -n "$run1_id" && -n "$run2_id" && "$run1_id" != "$run2_id" ]]; then
  ok "two consecutive updates get distinct run ids ($run1_id vs $run2_id)"
else
  bad "run ids not distinct/absent (run1=$run1_id run2=$run2_id)"
fi
rm -rf "$sb" "$stub_dir" "$status_dir"

# ---------------------------------------------------------------------------
echo "== 23. FIX-207: doctor judges health by ENABLED compose services (no hardcoded 4/4) =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# config lists the ENABLED services (LUMITEST_NO_RSSHUB=1 simulates an
# operator override that removed rsshub); inspect fails only for
# $LUMITEST_ABSENT (container missing/stopped), else healthy.
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  compose)
    case "$*" in
      *" config"*)
        if [ "${LUMITEST_NO_RSSHUB:-0}" = "1" ]; then
          printf '{"name": "lumirss-prod", "services": {"web": {}, "bff": {}, "freshrss": {}}}'
        else
          printf '{"name": "lumirss-prod", "services": {"web": {}, "bff": {}, "freshrss": {}, "rsshub": {}}}'
        fi;;
      *) exit 0;;
    esac;;
  inspect)
    name=""; prev=""
    for a in "$@"; do
      case "$a" in lumirss-*) name="$a";; esac
      prev="$a"
    done
    [ -n "${LUMITEST_ABSENT:-}" ] && [ "$name" = "$LUMITEST_ABSENT" ] && exit 1
    case "$*" in
      *OOMKilled*) echo false;;
      *RestartCount*) echo 0;;
      *"State.Health"*) echo none;;
      *) echo running;;
    esac;;
  ps) exit 0;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
run_doctor207() { # run_doctor207 [env assignments…] -> doctor output
  (cd "$sb" && cp -f .env.prod.example .env.prod \
    && env PATH="$stub_dir:$PATH" "$@" ./lumirss doctor 2>&1)
}
d_out="$(run_doctor207)"
assert_eq "all four services up -> doctor exits 0" "0" "$?"
assert_contains "each enabled service checked individually" "rsshub running" "$d_out"
assert_not_contains "healthy stack has no FAIL" "FAIL " "$d_out"
d_out="$(run_doctor207 LUMITEST_ABSENT=lumirss-rsshub)"
assert_eq "optional rsshub down -> doctor still exits 0 (no false missing alarm)" "0" "$?"
assert_contains "optional absence is reported as INFO, not a failure" \
  "rsshub not running (optional service" "$d_out"
assert_not_contains "optional absence is never a FAIL" "FAIL " "$d_out"
d_out="$(run_doctor207 LUMITEST_NO_RSSHUB=1)"
assert_eq "service removed from compose -> doctor exits 0" "0" "$?"
assert_not_contains "disabled service is not reported missing at all" "rsshub not running" "$d_out"
d_out="$(run_doctor207 LUMITEST_ABSENT=lumirss-bff)"
assert_eq "critical bff missing -> doctor exits 1 (no missed alarm)" "1" "$?"
assert_contains "critical absence is a FAIL naming the service" \
  "bff not running (state: absent) — core dependency" "$d_out"
d_out="$(run_doctor207 LUMITEST_ABSENT=lumirss-web)"
assert_eq "critical web missing -> doctor exits 1" "1" "$?"
assert_contains "web absence is a FAIL" "web not running" "$d_out"
rm -rf "$sb" "$stub_dir"

# ---------------------------------------------------------------------------
echo "== 24. FIX-198: doctor reports live and ready separately (live != ready) =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  compose)
    case "$*" in
      *" config"*) printf '{"name": "lumirss-prod", "services": {"web": {}, "bff": {}, "freshrss": {}, "rsshub": {}}}';;
      *" exec"*)
        # LUMITEST_BFF_DOWN=1 -> the bff process answers nothing (both
        # health probes fail); else exec succeeds like a healthy bff.
        [ -n "${LUMITEST_BFF_DOWN:-}" ] && exit 1
        exit 0;;
      *) exit 0;;
    esac;;
  inspect)
    name=""
    for a in "$@"; do case "$a" in lumirss-*) name="$a";; esac; done
    [ -n "${LUMITEST_ABSENT:-}" ] && [ "$name" = "$LUMITEST_ABSENT" ] && exit 1
    case "$*" in
      *OOMKilled*) echo false;;
      *RestartCount*) echo 0;;
      *"State.Health"*) echo none;;
      *) echo running;;
    esac;;
  ps) exit 0;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
d_out="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" ./lumirss doctor 2>&1)"
assert_eq "healthy bff -> doctor exits 0" "0" "$?"
assert_contains "live checked separately (PASS when process answers)" "bff live (process up)" "$d_out"
assert_contains "ready checked separately with its real meaning (sqlite usable)" "bff ready (lumi.sqlite usable)" "$d_out"
d_out="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMITEST_BFF_DOWN=1 ./lumirss doctor 2>&1)"
assert_eq "dead bff probes are WARN-only (doctor still exits 0)" "0" "$?"
assert_contains "live failure reported honestly" "bff live not OK" "$d_out"
assert_contains "ready failure distinguishes itself from live" \
  "live above may still be true" "$d_out"
assert_not_contains "no FAIL on a dead bff (WARN semantics unchanged)" "FAIL " "$d_out"
rm -rf "$sb" "$stub_dir"

# ---------------------------------------------------------------------------
echo "== 25. FIX-199: update completion is VERIFIED (version endpoint + image digests) =="
mk_verify_stub() { # mk_verify_stub DIR COMMIT_MODE DIGEST_MODE
  # COMMIT_MODE: ok | mismatch | empty ; DIGEST_MODE: ok | mismatch
  local dir="$1" cmode="$2" dmode="$3"
  mkdir -p "$dir"
  cat > "$dir/docker" <<STUB
#!/bin/sh
cmd="\$1"; [ \$# -gt 0 ] && shift
case "\$cmd" in
  info) exit 0;;
  run) exit 0;;
  image)
    case "\$*" in
      *inspect*) echo "sha256:pulled-image-id";;
      *) exit 0;;
    esac;;
  inspect)
    case "\$*" in
      *"{{.Image}}"*) echo "sha256:$([ "$dmode" = "mismatch" ] && echo running-image-id || echo pulled-image-id)";;
      *) echo healthy;;
    esac;;
  ps) exit 0;;
  compose)
    case "\$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *" pull"*) echo " Pulled";;
      *" exec"*)
        case "$cmode" in
          mismatch) echo '{"commit": "other-commit", "version": "2.0.1"}';;
          empty)    exit 0;;
          *)        echo '{"commit": "rel208sha", "version": "2.0.1"}';;
        esac;;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
  chmod +x "$dir/docker"
}
run_verify_update() { # run_verify_update STUBDIR STATUSFILE OUTFILE
  (cd "$sb" && cp -f .env.prod.example .env.prod \
    && env PATH="$1:$PATH" LUMIRSS_DEPLOY_STATUS_FILE="$2" \
       LUMIRSS_EXPECTED_COMMIT=rel208sha ./lumirss update > "$3" 2>&1)
}

sb="$(new_sandbox)"
mk_verify_stub "$sb/stub-ok" ok ok
v_status="$(mktemp -d)/v-ok.json"
run_verify_update "$sb/stub-ok" "$v_status" "$sb/out-ok.txt"
assert_eq "verified update exits 0" "0" "$?"
assert_contains "completion message states verification" "update complete (verified" "$(cat "$sb/out-ok.txt")"
assert_contains "status records verify ok + result success" "ok success" \
  "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["stages"]["verify"]["status"], d["result"]["status"])' "$v_status" 2>/dev/null || echo broken)"

mk_verify_stub "$sb/stub-commit" mismatch ok
v_status="$(mktemp -d)/v-commit.json"
rc=0; run_verify_update "$sb/stub-commit" "$v_status" "$sb/out-commit.txt" || rc=$?
assert_eq "commit mismatch -> update exits 1" "1" "$rc"
assert_contains "failure names the commit mismatch" "version/commit mismatch" "$(cat "$sb/out-commit.txt")"
assert_contains "status records verify failed + result failed" "failed failed" \
  "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["stages"]["verify"]["status"], d["result"]["status"])' "$v_status" 2>/dev/null || echo broken)"
assert_contains "failure points at manual rollback" "'./lumirss rollback'" "$(cat "$sb/out-commit.txt")"

mk_verify_stub "$sb/stub-digest" ok mismatch
v_status="$(mktemp -d)/v-digest.json"
rc=0; run_verify_update "$sb/stub-digest" "$v_status" "$sb/out-digest.txt" || rc=$?
assert_eq "image-digest mismatch -> update exits 1" "1" "$rc"
assert_contains "failure names the digest mismatch and the container" \
  "NOT running the pinned image" "$(cat "$sb/out-digest.txt")"

mk_verify_stub "$sb/stub-unreach" empty ok
v_status="$(mktemp -d)/v-unreach.json"
rc=0; run_verify_update "$sb/stub-unreach" "$v_status" "$sb/out-unreach.txt" || rc=$?
assert_eq "version endpoint unreachable -> update exits 1" "1" "$rc"
assert_contains "failure names the unreachable version endpoint" \
  "unreachable through the compose network" "$(cat "$sb/out-unreach.txt")"
rm -rf "$sb"

# ---------------------------------------------------------------------------
echo "== 26. FIX-202: restore stops ALL writers of the volume it overwrites =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"
r202_log="$(mktemp)"
cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
# logging stub: compose stop/start are recorded; containers are never real
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
case "$cmd" in
  info) exit 0;;
  run) exit 0;;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *) exit 0;;   # stop/start/exec succeed
    esac;;
  *) exit 0;;
esac
STUB
chmod +x "$stub_dir/docker"
mkdir -p "$sb/bk-frs" "$sb/bk-lumi"
printf 'frs-canary\n' > "$sb/bk-frs/frs.txt"
printf 'lumi-canary\n' > "$sb/bk-lumi/lumi.txt"
tar -C "$sb/bk-frs" -czf "$sb/bk-frs/freshrss-data.files.tar.gz" frs.txt
tar -C "$sb/bk-lumi" -czf "$sb/bk-lumi/lumi-data.files.tar.gz" lumi.txt
(cd "$sb" && cp -f .env.prod.example .env.prod)
frs_rc=0
(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$r202_log" \
  ./lumirss restore "$sb/bk-frs/freshrss-data.files.tar.gz" --yes >/dev/null 2>&1) || frs_rc=$?
assert_eq "freshrss-data restore exits 0" "0" "$frs_rc"
assert_contains "freshrss cron writer is stopped before overwrite" "stop bff freshrss" "$(cat "$r202_log")"
assert_contains "both writers restarted afterwards" "start bff freshrss" "$(cat "$r202_log")"
stop_line="$(grep -n "stop bff freshrss" "$r202_log" | head -1 | cut -d: -f1)"
run_line="$(grep -nE "docker run .*freshrss-data" "$r202_log" | head -1 | cut -d: -f1)"
if [[ -n "$stop_line" && -n "$run_line" && "$stop_line" -lt "$run_line" ]]; then
  ok "stop happens before the volume-mutating container runs"
else
  bad "restore container may run before writers stopped (stop=$stop_line run=$run_line)"
fi
: > "$r202_log"
lumi_rc=0
(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$r202_log" \
  ./lumirss restore "$sb/bk-lumi/lumi-data.files.tar.gz" --yes >/dev/null 2>&1) || lumi_rc=$?
assert_eq "lumi-data restore exits 0" "0" "$lumi_rc"
assert_contains "lumi-data restore stops its writer (bff)" "stop bff" "$(cat "$r202_log")"
assert_not_contains "lumi-data restore does not stop freshrss (not a writer of that volume)" \
  "stop bff freshrss" "$(cat "$r202_log")"
rm -rf "$sb" "$stub_dir" "$r202_log"

# ---------------------------------------------------------------------------
echo
echo "deploy-lifecycle tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
exit 0
