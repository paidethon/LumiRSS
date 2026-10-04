#!/usr/bin/env bash
# Single-container (all-in-one) topology tests — R05 step 2 integration:
#   - docker-compose.allinone.yml structural shape (one service, loopback-
#     only publish, VERSION-pinned default tag, both volumes, no build:)
#   - deploy --single dry-run persists LUMIRSS_SINGLE=1; the
#     --single + --external-caddy combination is refused
#   - update --single against a stub docker: pulls ONLY the allinone image,
#     brings the single compose up, verifies, writes topology:"single"
#     progress JSON; pull failure aborts with the old stack untouched
#   - migrate-single: backup gate → pull → prod down (never -v) → allinone
#     up → health/verify → LUMIRSS_SINGLE=1; aborts BEFORE touching the
#     stack when the backup or the pull fails
#   - rollback-single: allinone down → previous 4-container stack up (env
#     + tag + overlays restored); refuses an unverifiable manifest
#   - freshrss-init: execs the right container per topology and runs
#     access-permissions.sh after create-user (root:root user-dir fix)
#   - status / doctor consume the lumirss-health JSON in single topology
#   - release bundle carries docker-compose.allinone.yml + ALL-IN-ONE.md,
#     covered by SHA256SUMS
#   - check-version.py refuses an allinone default-tag drift
# Run from anywhere: tests/deploy/run-single-topology-tests.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0
VERSION="$(cat "$REPO_ROOT/VERSION")"

ok()  { printf '  ok   %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n' "$1"; FAIL=$((FAIL + 1)); }
assert_eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 — expected [$2] got [$3]"; fi; }
assert_contains() { if [[ "$3" == *"$2"* ]]; then ok "$1"; else bad "$1 — missing [$2]"; fi; }
assert_not_contains() { if [[ "$3" != *"$2"* ]]; then ok "$1"; else bad "$1 — unexpected [$2]"; fi; }

new_sandbox() { # isolated copy so tests never touch a developer .env.prod
  local dir; dir="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-single-test.XXXXXX")"
  cp "$REPO_ROOT/lumirss" "$dir/"
  cp "$REPO_ROOT/docker-compose.prod.yml" "$REPO_ROOT/docker-compose.allinone.yml" \
     "$REPO_ROOT/docker-compose.external-caddy.yml" "$REPO_ROOT/docker-compose.obsidian.yml" "$dir/"
  cp "$REPO_ROOT/.env.prod.example" "$dir/.env.prod.example"
  printf '%s\n' "$dir"
}

# Parameterized stub docker: every call is logged; behavior flips via env.
# Compose is ALWAYS invoked with -f files first (DC_ARGS), so subcommand
# matching runs against the full argument string (same shape as
# run-deploy-tests.sh stubs).
#   LUMITEST_FAIL_RUN=1    docker run fails          (backup gate abort test)
#   LUMITEST_FAIL_PULL=1   pull + image inspect fail (pull gate abort test;
#                          a failed pull must NOT fall back to local images)
#   LUMITEST_PS_LINE=...   compose ps output         (status "is it running")
#   LUMITEST_HEALTH_JSON=… exec lumirss-health fixture
make_stub() { # dir
  cat > "$1/docker" <<'STUB'
#!/bin/sh
echo "docker $*" >> "${LUMIRSS_TEST_DOCKER_LOG:?}"
cmd="$1"; [ $# -gt 0 ] && shift
# hex-only image IDs: the CLI validates recorded image ids against
# ^sha256:[0-9a-f]{6,64}$ before pinning them into rollback manifests.
IMG_ID="sha256:1111111111111111111111111111111111111111111111111111111111111111"
case "$cmd" in
  info) exit 0;;
  pull)
    if [ -n "${LUMITEST_FAIL_PULL:-}" ]; then
      echo 'Error response from daemon: pull refused (test stub)' >&2; exit 1
    fi
    exit 0;;
  run)
    if [ -n "${LUMITEST_FAIL_RUN:-}" ]; then exit 1; fi
    exit 0;;
  ps) exit 0;;
  tag) exit 0;;
  exec)
    case "$*" in
      *lumirss-health*) printf '%s\n' "${LUMITEST_HEALTH_JSON:-}";;
      *) exit 0;;
    esac;;
  inspect)
    case "$*" in
      *"{{.Image}}"*) echo "${LUMITEST_RUNNING_ID:-$IMG_ID}";;
      *"{{.State.Status}}"*) echo "running";;
      *"State.Health"*) echo "healthy";;
      *"{{.State.OOMKilled}}"*) echo "false";;
      *"{{.RestartCount}}"*) echo "0";;
      *) exit 0;;
    esac;;
  image)
    if [ -n "${LUMITEST_FAIL_PULL:-}" ]; then exit 1; fi
    echo "${LUMITEST_IMAGE_ID:-$IMG_ID}";;
  compose)
    case "$*" in
      *" config"*) echo '{"name": "lumirss-prod"}';;
      *" ps"*) printf '%s\n' "${LUMITEST_PS_LINE:-}";;
      *" pull"*)
        if [ -n "${LUMITEST_FAIL_PULL:-}" ]; then exit 1; fi
        exit 0;;
      *" exec "*)
        case "$*" in
          *lumirss-health*) printf '%s\n' "${LUMITEST_HEALTH_JSON:-}";;
          *schema_migrations*) printf '%s\n' "${LUMITEST_SCHEMA:-}";;
          *health/live*|*health/ready*) exit 0;;
          *api/v1/version*) echo '{"commit": "stub-commit", "version": "test"}';;
          *) exit 0;;
        esac;;
      *) exit 0;;
    esac;;
  *) exit 0;;
esac
STUB
  chmod +x "$1/docker"
}

ALLINONE_UP_LINE="compose -f docker-compose.allinone.yml up -d --remove-orphans"

# ---------------------------------------------------------------------------
echo "== 1. docker-compose.allinone.yml structural shape =="
export EXPECTED_VERSION="$VERSION"
render_aio() { # render the allinone compose from an isolated sandbox dir
  local dir rc
  dir="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-single-render.XXXXXX")"
  cp "$REPO_ROOT/docker-compose.allinone.yml" "$dir/"
  cp "$REPO_ROOT/.env.prod.example" "$dir/.env.prod"
  ( cd "$dir" && docker compose -f docker-compose.allinone.yml config --format json )
  rc=$?
  rm -rf "$dir"
  return $rc
}
aio_json="$(render_aio)"
if [[ $? -eq 0 ]]; then ok "allinone compose renders"; else bad "allinone compose render failed"; fi
python3 - "$aio_json" <<'PY' && ok "one service, loopback-only :80 publish, no build:, VERSION tag, both volumes" \
|| bad "allinone compose shape deviates"
import json, os, sys

cfg = json.loads(sys.argv[1])
services = cfg.get("services", {})
assert sorted(services) == ["lumirss"], services
svc = services["lumirss"]
assert "build" not in svc, "allinone stack must be prebuilt-only"
assert svc["image"] == "ghcr.io/paidethon/lumirss/lumirss-allinone:" + os.environ["EXPECTED_VERSION"], svc["image"]
ports = sorted(
    "{}:{}".format(p.get("host_ip", ""), p.get("published", ""))
    for p in (svc.get("ports") or [])
)
assert ports == ["127.0.0.1:18080"], ports
vols = sorted(
    (v.get("source") if isinstance(v, dict) else v.split(":")[0])
    for v in (svc.get("volumes") or [])
    if (v.get("source") if isinstance(v, dict) else str(v)).startswith(("lumi-", "freshrss-"))
)
assert vols == ["freshrss-data", "lumi-data"], vols
assert svc.get("mem_limit"), "allinone container must carry its memory limit"
PY
aio_json="$(render_aio)"
python3 - "$aio_json" <<'PY' && ok "default tag equals VERSION (check-version.py contract)" || bad "allinone default tag != VERSION"
import json, os, sys
svc = json.loads(sys.argv[1])["services"]["lumirss"]
assert svc["image"].endswith(":" + os.environ["EXPECTED_VERSION"]), svc["image"]
PY

# ---------------------------------------------------------------------------
echo "== 2. deploy --single dry-run + flag conflict =="
sb="$(new_sandbox)"
d2="$(cd "$sb" && ./lumirss deploy --single --dry-run 2>&1)"; rc=$?
assert_eq "deploy --single --dry-run exits 0" "0" "$rc"
assert_eq "LUMIRSS_SINGLE=1 persisted by the dry run" "1" "$(grep -cE '^LUMIRSS_SINGLE=1$' "$sb/.env.prod")"
c2="$(cd "$sb" && ./lumirss deploy --single --external-caddy 2>&1)"; rc=$?
assert_eq "--single + --external-caddy refuses" "1" "$rc"
assert_contains "refusal explains the external-caddy-only construction" \
  "external-caddy-only by construction" "$c2"
rm -rf "$sb"

# ---------------------------------------------------------------------------
echo "== 3. update --single: allinone-only pull + verified switch + topology JSON =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
u_log="$(mktemp)"; status_file="$sb/deploy-status.json"
u3="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && printf 'LUMIRSS_SINGLE=1\n' >> .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$u_log" \
     LUMIRSS_IMAGE_TAG=singletag LUMIRSS_DEPLOY_STATUS_FILE="$status_file" \
     LUMITEST_PS_LINE="lumirss-app   running" \
     ./lumirss update 2>&1)"; rc=$?
assert_eq "update --single completes" "0" "$rc"
assert_contains "update reports verified completion" "update complete" "$u3"
assert_contains "pulls the allinone image" \
  "pull ghcr.io/paidethon/lumirss/lumirss-allinone:singletag" "$(cat "$u_log")"
assert_not_contains "never pulls the 4-container bff image" \
  "pull ghcr.io/paidethon/lumirss/lumirss-bff" "$(cat "$u_log")"
assert_contains "brings the single compose up" "$ALLINONE_UP_LINE" "$(cat "$u_log")"
if grep -qE "compose -f docker-compose\.prod\.yml up" "$u_log"; then
  bad "update --single touched the 4-container compose"
else
  ok "update --single never references the 4-container compose"
fi
python3 - "$status_file" <<'PY' && ok "deploy-status JSON: topology=single, result=success" \
|| bad "deploy-status JSON wrong"
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("topology") == "single", d.get("topology")
assert d.get("result", {}).get("status") == "success", d.get("result")
for stage in ("backup", "pull", "migrate", "health", "verify"):
    assert d["stages"][stage]["status"] == "ok", (stage, d["stages"].get(stage))
PY
rm -rf "$sb" "$stub_dir" "$u_log"

# ---------------------------------------------------------------------------
echo "== 4. update --single: pull failure aborts, nothing switched =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
p_log="$(mktemp)"
u4="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && printf 'LUMIRSS_SINGLE=1\n' >> .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$p_log" LUMITEST_FAIL_PULL=1 \
     LUMIRSS_IMAGE_TAG=singletag ./lumirss update 2>&1)"; rc=$?
assert_eq "pull failure aborts update --single" "1" "$rc"
assert_contains "abort names the preserved old stack" "still running and untouched" "$u4"
if grep -qE "compose .* up " "$p_log"; then
  bad "pull failure still ran compose up"
else
  ok "no compose up after the pull failure"
fi
rm -rf "$sb" "$stub_dir" "$p_log"

# ---------------------------------------------------------------------------
echo "== 5. migrate-single: backup → pull → prod down (no -v) → allinone up → verified =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
m_log="$(mktemp)"
m5="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && printf 'LUMIRSS_EXTERNAL_CADDY=1\nLUMIRSS_UPSTREAM_PORT=18080\n' >> .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$m_log" \
     LUMIRSS_BACKUP_DIR="$sb/backups" LUMIRSS_IMAGE_TAG=singletag \
     LUMIRSS_DEPLOY_STATUS_FILE="$sb/deploy-status.json" \
     LUMITEST_PS_LINE="lumirss-app   running" \
     ./lumirss migrate-single 2>&1)"; rc=$?
assert_eq "migrate-single completes" "0" "$rc"
assert_contains "migration reports completion" "migration complete" "$m5"
[[ -s "$sb/backups/LATEST" ]] && ok "backup gate ran (backups/LATEST written)" \
  || bad "backup gate did not run"
down_line="$(grep -nE "compose -f docker-compose\.prod\.yml .* down" "$m_log" | head -1 | cut -d: -f1)"
aio_line="$(grep -nF "$ALLINONE_UP_LINE" "$m_log" | head -1 | cut -d: -f1)"
if [[ -n "$down_line" && -n "$aio_line" && "$down_line" -lt "$aio_line" ]]; then
  ok "old stack stopped BEFORE the single container started"
else
  bad "switch order wrong (down=$down_line, allinone up=$aio_line)"
fi
if grep -qE "down .*-v" "$m_log"; then
  bad "migrate-single ran a volume-destroying down"
else
  ok "old stack stopped WITHOUT -v (volumes kept)"
fi
assert_contains "pull happens before the switch (old stack still up)" \
  "pulling prebuilt images" "$m5"
assert_eq "LUMIRSS_SINGLE=1 persisted" "1" "$(grep -cE '^LUMIRSS_SINGLE=1$' "$sb/.env.prod")"
assert_eq "LUMIRSS_IMAGE_TAG pinned to the migrated release" "singletag" \
  "$(grep -E '^LUMIRSS_IMAGE_TAG=' "$sb/.env.prod" | cut -d= -f2-)"
python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("command") == "migrate-single", d.get("command")
assert d.get("topology") == "single", d.get("topology")
assert d.get("result", {}).get("status") == "success", d.get("result")
' "$sb/deploy-status.json" 2>/dev/null \
  && ok "migrate-single wrote its own verified progress JSON" \
  || bad "migrate-single progress JSON wrong/missing"
# Rollback point captured from the RUNNING multi stack BEFORE the switch.
python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("previousImageTag") == "singletag", d.get("previousImageTag")
assert str(d.get("previousImageIdBff") or "").startswith("sha256:"), d
' "$sb/backups/.rollback-manifest.json" 2>/dev/null \
  && ok "rollback manifest pins the pre-migration stack" \
  || bad "rollback manifest missing/wrong"
rm -rf "$sb" "$stub_dir" "$m_log"

# ---------------------------------------------------------------------------
echo "== 6. migrate-single: backup-gate failure aborts BEFORE touching the stack =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
b_log="$(mktemp)"
m6="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$b_log" LUMITEST_FAIL_RUN=1 \
     ./lumirss migrate-single 2>&1)"; rc=$?
assert_eq "backup failure aborts the migration" "1" "$rc"
assert_contains "abort states nothing was changed" \
  "NOTHING was changed; the 4-container stack keeps running" "$m6"
if grep -qE "compose .* down|compose -f docker-compose\.allinone\.yml up" "$b_log"; then
  bad "backup-gate abort still stopped/started containers"
else
  ok "backup-gate abort never stopped the old stack nor started the single container"
fi
assert_eq "topology not persisted on abort" "0" "$(grep -cE '^LUMIRSS_SINGLE=1$' "$sb/.env.prod")"
rm -rf "$sb" "$stub_dir" "$b_log"

# ---------------------------------------------------------------------------
echo "== 7. migrate-single: pull-gate failure aborts, old stack still running =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
g_log="$(mktemp)"
m7="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$g_log" LUMITEST_FAIL_PULL=1 \
     LUMIRSS_IMAGE_TAG=singletag ./lumirss migrate-single 2>&1)"; rc=$?
assert_eq "pull failure aborts the migration" "1" "$rc"
assert_contains "abort states nothing was changed" \
  "NOTHING was changed; the 4-container stack keeps running" "$m7"
if grep -qE "compose -f docker-compose\.prod\.yml down" "$g_log"; then
  bad "pull-gate abort stopped the old stack"
else
  ok "pull-gate abort never stopped the old stack"
fi
rm -rf "$sb" "$stub_dir" "$g_log"

# ---------------------------------------------------------------------------
echo "== 8. rollback-single: allinone down → previous multi stack up (env/tag restored) =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
r_log="$(mktemp)"
mkdir -p "$sb/backups"
cp -f "$sb/.env.prod.example" "$sb/.env.prod"
printf 'LUMIRSS_SINGLE=1\n' >> "$sb/.env.prod"
cp -f "$sb/.env.prod.example" "$sb/backups/.env.prod.previous"
printf 'LUMIRSS_EXTERNAL_CADDY=1\n' >> "$sb/backups/.env.prod.previous"
printf 'oldtag\n' > "$sb/backups/.image-tag.previous"
cat > "$sb/backups/.rollback-manifest.json" <<'JSON'
{
 "schema": "lumirss-rollback-manifest/v1",
 "previousImageTag": "oldtag",
 "previousImageIdBff": null,
 "previousImageIdWeb": null,
 "preUpdateSchemaVersion": null,
 "runId": null,
 "writtenAt": "2026-10-02T00:00:00+00:00"
}
JSON
r8="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$r_log" \
     LUMIRSS_BACKUP_DIR="$sb/backups" LUMITEST_PS_LINE="lumirss-web   running" \
     ./lumirss rollback-single --yes 2>&1)"; rc=$?
assert_eq "rollback-single completes" "0" "$rc"
assert_contains "rollback reports completion" "rollback-single complete" "$r8"
aio_down="$(grep -nE "compose -f docker-compose\.allinone\.yml down" "$r_log" | head -1 | cut -d: -f1)"
multi_up="$(grep -nE "compose -f docker-compose\.prod\.yml -f docker-compose\.external-caddy\.yml up" "$r_log" | head -1 | cut -d: -f1)"
if [[ -n "$aio_down" && -n "$multi_up" && "$aio_down" -lt "$multi_up" ]]; then
  ok "single container stopped BEFORE the 4-container stack restarted (external overlay reapplied)"
else
  bad "rollback order/overlay wrong (down=$aio_down, up=$multi_up)"
fi
if grep -qE "down .*-v" "$r_log"; then
  bad "rollback-single ran a volume-destroying down"
else
  ok "rollback-single never destroys volumes"
fi
assert_eq "LUMIRSS_SINGLE cleared" "0" "$(grep -cE '^LUMIRSS_SINGLE=1$' "$sb/.env.prod")"
assert_eq "previous tag re-pinned" "oldtag" \
  "$(grep -E '^LUMIRSS_IMAGE_TAG=' "$sb/.env.prod" | cut -d= -f2-)"
rm -rf "$sb" "$stub_dir" "$r_log"

# ---------------------------------------------------------------------------
echo "== 8b. rollback-single schema gate: forward-migrated DB needs --yes =="
rollback_single_with() { # manifest-pre-schema current-schema extra-args logfile
  sb="$(new_sandbox)"
  stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
  local pre="$1" cur="$2" extra="$3" logf="$4"
  mkdir -p "$sb/backups"
  cp -f "$sb/.env.prod.example" "$sb/.env.prod"
  printf 'LUMIRSS_SINGLE=1\n' >> "$sb/.env.prod"
  printf 'oldtag\n' > "$sb/backups/.image-tag.previous"
  cat > "$sb/backups/.rollback-manifest.json" <<JSON
{
 "schema": "lumirss-rollback-manifest/v1",
 "previousImageTag": "oldtag",
 "previousImageIdBff": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
 "previousImageIdWeb": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
 "preUpdateSchemaVersion": $pre,
 "runId": null,
 "writtenAt": "2026-10-02T00:00:00+00:00"
}
JSON
  ( cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$logf" \
      LUMIRSS_BACKUP_DIR="$sb/backups" LUMITEST_SCHEMA="$cur" \
      LUMITEST_PS_LINE="lumirss-web   running" \
      ./lumirss rollback-single $extra 2>&1 )
  local rc=$?
  rm -rf "$sb" "$stub_dir"
  echo "$rc"
}
rb_log="$(mktemp)"
rc8b="$(rollback_single_with 100 200 "--yes" "$rb_log" | tail -1)"
assert_eq "schema-forward rollback proceeds with explicit --yes" "0" "$rc8b"
grep -qE "compose -f docker-compose\.allinone\.yml down" "$rb_log" \
  && grep -qE "compose -f docker-compose\.prod\.yml up" "$rb_log" \
  && ok "explicit --yes still performs the full switch" \
  || bad "schema-forward --yes did not perform the switch"
rb2_log="$(mktemp)"
out8b="$(rollback_single_with 100 200 "" "$rb2_log")"
rc8b2="$(printf '%s\n' "$out8b" | tail -1)"
assert_eq "schema-forward rollback refuses without --yes (non-interactive)" "1" "$rc8b2"
assert_contains "refusal discloses the forward migration" \
  "the old 4-container images cannot undo those migrations" "$out8b"
if grep -qE "compose .* down" "$rb2_log"; then
  bad "schema-forward refusal still stopped the single container"
else
  ok "schema-forward refusal switched nothing"
fi
# Equal schema = the normal same-version migration rollback: proceeds.
rb3_log="$(mktemp)"
rc8c="$(rollback_single_with 137 137 "--yes" "$rb3_log" | tail -1)"
assert_eq "unchanged schema rolls back cleanly" "0" "$rc8c"
rm -f "$rb_log" "$rb2_log" "$rb3_log"

# ---------------------------------------------------------------------------
echo "== 9. rollback-single refuses an unverifiable manifest =="
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
rf_log="$(mktemp)"
mkdir -p "$sb/backups"
cp -f "$sb/.env.prod.example" "$sb/.env.prod"
printf 'LUMIRSS_SINGLE=1\n' >> "$sb/.env.prod"
printf 'oldtag\n' > "$sb/backups/.image-tag.previous"
cat > "$sb/backups/.rollback-manifest.json" <<'JSON'
{
 "schema": "lumirss-rollback-manifest/v1",
 "previousImageTag": "oldtag",
 "previousImageIdBff": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
 "previousImageIdWeb": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
 "preUpdateSchemaVersion": null,
 "runId": null,
 "writtenAt": "2026-10-02T00:00:00+00:00"
}
JSON
r9="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$rf_log" \
     LUMIRSS_BACKUP_DIR="$sb/backups" ./lumirss rollback-single --yes 2>&1)"; rc=$?
assert_eq "manifest without schema truth refuses even with --yes" "1" "$rc"
assert_contains "refusal names the unverifiable state" "cannot be verified" "$r9"
if grep -qE "compose .* down" "$rf_log"; then
  bad "refused rollback still stopped the single container"
else
  ok "refused rollback switched nothing"
fi
rm -rf "$sb" "$stub_dir" "$rf_log"

# ---------------------------------------------------------------------------
echo "== 10. freshrss-init: per-topology exec target + access-permissions fix =="
# 10a. single topology: execs lumirss-app with an explicit FreshRSS workdir.
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
f_log="$(mktemp)"
f10="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && printf 'LUMIRSS_SINGLE=1\n' >> .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$f_log" ./lumirss freshrss-init 2>&1)"; rc=$?
assert_eq "single-topology freshrss-init exits 0" "0" "$rc"
assert_contains "execs the allinone container with an explicit FreshRSS workdir" \
  "exec -w /var/www/FreshRSS lumirss-app php ./cli/do-install.php" "$(cat "$f_log")"
create_line="$(grep -nF "create-user.php" "$f_log" | head -1 | cut -d: -f1)"
perm_line="$(grep -nF "access-permissions.sh" "$f_log" | head -1 | cut -d: -f1)"
if [[ -n "$create_line" && -n "$perm_line" && "$perm_line" -gt "$create_line" ]]; then
  ok "access-permissions.sh runs AFTER create-user (root:root user-dir fix)"
else
  bad "access-permissions.sh missing or misordered after create-user"
fi
rm -rf "$sb" "$stub_dir" "$f_log"
# 10b. multi topology: same fix inside lumirss-freshrss.
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
fm_log="$(mktemp)"
fm10="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$fm_log" ./lumirss freshrss-init 2>&1)"; rc=$?
assert_eq "multi-topology freshrss-init exits 0" "0" "$rc"
assert_contains "multi topology still execs lumirss-freshrss" \
  "exec lumirss-freshrss php ./cli/do-install.php" "$(cat "$fm_log")"
create_line="$(grep -nF "create-user.php" "$fm_log" | head -1 | cut -d: -f1)"
perm_line="$(grep -nF "access-permissions.sh" "$fm_log" | head -1 | cut -d: -f1)"
if [[ -n "$create_line" && -n "$perm_line" && "$perm_line" -gt "$create_line" ]]; then
  ok "multi topology applies the same access-permissions fix"
else
  bad "multi topology missing the access-permissions fix"
fi
rm -rf "$sb" "$stub_dir" "$fm_log"

# ---------------------------------------------------------------------------
echo "== 11. status / doctor consume lumirss-health JSON (single topology) =="
health_fixture='{"freshrss-init":{"state":"done","pid":null,"http_ok":null,"last_actualize_epoch":null},"freshrss-php":{"state":"up","pid":10,"http_ok":true,"last_actualize_epoch":null},"freshrss-cron":{"state":"up","pid":11,"http_ok":null,"last_actualize_epoch":1759366980},"bff":{"state":"up","pid":12,"http_ok":true,"last_actualize_epoch":null},"caddy":{"state":"up","pid":13,"http_ok":null,"last_actualize_epoch":null},"rsshub":{"state":"down","pid":null,"http_ok":false,"last_actualize_epoch":null},"memory":{"limit":"1200m","used":"400000000"}}'
sb="$(new_sandbox)"
stub_dir="$(mktemp -d)"; make_stub "$stub_dir"
s_log="$(mktemp)"
s11="$(cd "$sb" && cp -f .env.prod.example .env.prod \
  && printf 'LUMIRSS_SINGLE=1\nDOMAIN=reader.example.com\n' >> .env.prod \
  && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$s_log" \
     LUMITEST_PS_LINE="lumirss-app   running" LUMITEST_HEALTH_JSON="$health_fixture" \
     ./lumirss status 2>&1)"
assert_contains "status identifies the single topology" "topology: single" "$s11"
assert_contains "status summarizes per-service health" "bff=up/http-ok" "$s11"
assert_contains "status marks the degraded optional service" "rsshub=down" "$s11"
assert_contains "status probes health via the allinone exec" \
  "exec lumirss-app lumirss-health" "$(cat "$s_log")"
d11="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$s_log" \
     LUMITEST_PS_LINE="lumirss-app   running" \
     LUMITEST_HEALTH_JSON="$health_fixture" ./lumirss doctor 2>&1)"; rc=$?
assert_eq "doctor passes with a healthy allinone fixture (rsshub down is INFO-only)" "0" "$rc"
assert_contains "doctor checks the single container" "lumirss-app (single container) running" "$d11"
assert_contains "doctor consumes the health JSON for bff" "bff up + http ok" "$d11"
assert_contains "doctor treats rsshub-down as optional" "rsshub not up (optional service" "$d11"
bad_fixture='{"freshrss-init":{"state":"done","pid":null,"http_ok":null,"last_actualize_epoch":null},"freshrss-php":{"state":"up","pid":10,"http_ok":false,"last_actualize_epoch":null},"freshrss-cron":{"state":"down","pid":null,"http_ok":null,"last_actualize_epoch":null},"bff":{"state":"up","pid":12,"http_ok":false,"last_actualize_epoch":null},"caddy":{"state":"up","pid":13,"http_ok":null,"last_actualize_epoch":null},"rsshub":{"state":"up","pid":14,"http_ok":true,"last_actualize_epoch":null}}'
d11b="$(cd "$sb" && env PATH="$stub_dir:$PATH" LUMIRSS_TEST_DOCKER_LOG="$s_log" \
      LUMITEST_PS_LINE="lumirss-app   running" \
      LUMITEST_HEALTH_JSON="$bad_fixture" ./lumirss doctor 2>&1)"; rc=$?
assert_eq "doctor FAILs when the single-container core services degrade" "1" "$rc"
assert_contains "degraded bff is a hard failure" "bff degraded" "$d11b"
assert_contains "degraded freshrss-php is a hard failure" "freshrss-php degraded" "$d11b"
assert_contains "stopped cron is a warning, not green" \
  "freshrss-cron down — automatic feed refresh is disabled" "$d11b"
rm -rf "$sb" "$stub_dir" "$s_log"

# ---------------------------------------------------------------------------
echo "== 12. release bundle carries the allinone compose + instructions, SHA256SUMS-covered =="
work="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-single-bundle.XXXXXX")"
mkdir -p "$work/out"
cat > "$work/manifest.json" <<JSON
{
  "schema": "lumirss-release-manifest/v1",
  "name": "LumiRSS",
  "version": "$VERSION",
  "git_sha": "0123456789abcdef0123456789abcdef01234567",
  "generated_at": "2026-10-02T00:00:00Z",
  "images": {
    "bff": "ghcr.io/paidethon/lumirss/lumirss-bff@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "web": "ghcr.io/paidethon/lumirss/lumirss-web@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "allinone": "ghcr.io/paidethon/lumirss/lumirss-allinone@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "platform": "linux/amd64",
  "migrations": ["0001_baseline.sql"],
  "min_compat": null,
  "note": "test manifest"
}
JSON
if bash "$REPO_ROOT/scripts/assemble-release-bundle.sh" --out "$work/out" --manifest "$work/manifest.json" > /dev/null 2>&1; then
  ok "bundle assembly exits 0"
else
  bad "bundle assembly failed"
fi
bundle="$work/out/lumirss-release-bundle-$VERSION"
for f in docker-compose.allinone.yml ALL-IN-ONE.md; do
  [[ -s "$bundle/$f" ]] && ok "bundle carries $f" || bad "bundle missing $f"
done
( cd "$bundle" && sha256sum -c SHA256SUMS > /dev/null 2>&1 ) \
  && ok "SHA256SUMS verifies over the bundle incl. allinone files" || bad "SHA256SUMS broken"
for f in docker-compose.allinone.yml ALL-IN-ONE.md; do
  grep -q "  $f\$" "$bundle/SHA256SUMS" \
    && ok "SHA256SUMS covers $f" || bad "SHA256SUMS missing $f"
done
( cd "$bundle" && grep -q "LUMIRSS_IMAGE_TAG:-$VERSION" docker-compose.allinone.yml ) \
  && ok "bundle allinone compose pins the release tag" || bad "bundle allinone default tag wrong"
rm -rf "$work"

# ---------------------------------------------------------------------------
echo "== 13. check-version.py refuses an allinone default-tag drift =="
tree="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-single-vercheck.XXXXXX")"
mkdir -p "$tree/scripts" "$tree/services/bff/src/lumirss" "$tree/apps/web"
cp "$REPO_ROOT/scripts/check-version.py" "$tree/scripts/"
cp "$REPO_ROOT/VERSION" "$tree/"
cp "$REPO_ROOT/services/bff/pyproject.toml" "$tree/services/bff/"
cp "$REPO_ROOT/services/bff/src/lumirss/config.py" "$tree/services/bff/src/lumirss/"
cp "$REPO_ROOT/apps/web/package.json" "$tree/apps/web/"
cp "$REPO_ROOT/docker-compose.prod.yml" "$REPO_ROOT/docker-compose.allinone.yml" "$tree/"
if python3 "$tree/scripts/check-version.py" > /dev/null 2>&1; then
  ok "baseline copy passes (allinone default == VERSION)"
else
  bad "baseline check-version unexpectedly failed"
fi
sed -i "s/LUMIRSS_IMAGE_TAG:-$VERSION/LUMIRSS_IMAGE_TAG:-9.9.9/" "$tree/docker-compose.allinone.yml"
vout="$(python3 "$tree/scripts/check-version.py" 2>&1)"; rc=$?
assert_eq "allinone default-tag drift refuses" "1" "$rc"
assert_contains "refusal names docker-compose.allinone.yml" "docker-compose.allinone.yml" "$vout"
rm -rf "$tree"

# ---------------------------------------------------------------------------
# R3 兼容守卫：存量 freshrss_binding 存的是四容器 DNS 名
# （http://freshrss:80 / http://rsshub:1200）——单容器必须同时提供
# extra_hosts 名字映射与 Caddy Host 站点，否则迁移后文章全挂（v3.0.0
# 首发真实事故）。
grep -q 'extra_hosts' "$REPO_ROOT/docker-compose.allinone.yml" \
  && grep -q '"freshrss:127.0.0.1"' "$REPO_ROOT/docker-compose.allinone.yml" \
  && grep -q '"rsshub:127.0.0.1"' "$REPO_ROOT/docker-compose.allinone.yml" \
  && ok "allinone compose maps freshrss/rsshub hostnames to loopback" \
  || bad "allinone compose missing extra_hosts freshrss/rsshub"
grep -q 'http://freshrss,' "$REPO_ROOT/docker/all-in-one/Caddyfile.aio.template" \
  && grep -q 'http://rsshub {' "$REPO_ROOT/docker/all-in-one/Caddyfile.aio.template" \
  && ok "aio Caddy routes Host freshrss/rsshub to internal services" \
  || bad "aio Caddy template missing freshrss/rsshub Host sites"

# ---------------------------------------------------------------------------
echo
echo "single-topology tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
exit 0
