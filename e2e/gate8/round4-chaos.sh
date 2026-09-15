#!/usr/bin/env bash
# Round 4 故障注入 + 对抗探针（Gate 8 栈）。
#
# 验证目标（指令 §44/§45）：
# - optional 基础设施（FreshRSS / AI provider）故障不得拖垮 RSS Reader 主链路；
# - 对抗 URL（私网/元数据地址）在 clip / feed-preview / api-source 入口被
#   策略拒绝（fail-closed），绝不真拨号；
# - 结束后恢复所有容器，栈回到可用状态。
set -uo pipefail
cd "$(dirname "$0")/../.."
COMPOSE="docker compose -f e2e/gate8/docker-compose.e2e.yml"
BASE=http://127.0.0.1:8088
E2E_LOGIN="${E2E_LOGIN:-e2e-login-pwpw}"
INTERNAL_TOKEN="${E2E_INTERNAL_TOKEN:-e2e-internal-token-0123456789abcdef}"
COOKIE=$(mktemp)
RESULT=()
pass() { RESULT+=("PASS $1"); echo "PASS  $1"; }
fail() { RESULT+=("FAIL $1"); echo "FAIL  $1"; }

icurl() { local path="$1"; shift; curl -sS -b "$COOKIE" -H "X-Lumi-Token: $INTERNAL_TOKEN" -H "Origin: $BASE" "$@" "$BASE$path"; }

curl -sS -o /dev/null -c "$COOKIE" -H "Origin: $BASE" -H 'content-type: application/json' \
  -d "{\"password\": \"$E2E_LOGIN\"}" "$BASE/api/v1/auth/login"

restore() {
  $COMPOSE start freshrss >/dev/null 2>&1 || true
  $COMPOSE start ai >/dev/null 2>&1 || true
  rm -f "$COOKIE"
}
trap restore EXIT

echo "== 故障注入：FreshRSS 停机 =="
$COMPOSE stop freshrss >/dev/null 2>&1
sleep 2

code=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/" )
[[ "$code" == "200" ]] && pass "web shell still serves 200 with FreshRSS down" || fail "web shell got $code"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/api/v1/workspaces" -b "$COOKIE" -H "X-Lumi-Token: $INTERNAL_TOKEN" -H "Origin: $BASE")
[[ "$code" == "200" ]] && pass "workspaces API still 200 with FreshRSS down" || fail "workspaces got $code"
body=$(icurl /api/v1/entries?limit=5)
echo "$body" | grep -qE '"items"|"error"' && pass "entries API degrades to stable JSON (no hang/500-html)" || fail "entries: $body"
code=$(curl -sS -o /dev/null -w '%{http_code}' -b "$COOKIE" -H "X-Lumi-Token: $INTERNAL_TOKEN" -H "Origin: $BASE" "$BASE/api/v1/search?q=probe")
[[ "$code" == "200" || "$code" == "502" ]] && pass "search answers honestly (200 or stable 502) with FreshRSS down" || fail "search got $code"
ready=$($COMPOSE exec -T bff python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())")
echo "$ready" | grep -q freshrss && pass "health/ready reports freshrss component state" || fail "ready: $ready"

echo "== 对抗 URL：SSRF 边界（fail-closed） =="
for url in 'http://169.254.169.254/latest/meta-data/' 'http://127.0.0.1:8000/health/ready' 'http://localhost:5432'; do
  resp=$(icurl /api/v1/library/clips/fetch -X POST -H 'content-type: application/json' -d "{\"url\": \"$url\"}")
  echo "$resp" | grep -qE 'unsafe|forbidden|非公网|不允许|could not' \
    && pass "clip fetch refuses $url" || fail "clip fetch $url -> $resp"
done
resp=$(icurl /api/v1/feed-preview -X POST -H 'content-type: application/json' -d '{"feedUrl": "http://169.254.169.254/f.xml"}')
echo "$resp" | grep -qE 'unsafe_feed_url|unsafe|非公网' \
  && pass "feed-preview refuses metadata address" || fail "feed-preview -> $resp"
resp=$(icurl /api/v1/api-sources/preview -X POST -H 'content-type: application/json' -d '{"endpoint": "http://169.254.169.254/latest/meta-data/", "itemsExpr": "items"}')
echo "$resp" | grep -qE 'unsafe|forbidden|非公网|不允许|error' \
  && pass "api-source preview refuses metadata address" || fail "api-source preview -> $resp"

echo "== 恢复 FreshRSS，注入 AI provider 故障 =="
$COMPOSE start freshrss >/dev/null 2>&1
sleep 3
$COMPOSE stop ai >/dev/null 2>&1
sleep 1
code=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/")
[[ "$code" == "200" ]] && pass "web shell still 200 with AI provider down" || fail "web shell got $code"
body=$(icurl /api/v1/rag/status)
echo "$body" | grep -q '"enabled"' && pass "rag status honest with model infra down" || fail "rag status: $body"

$COMPOSE start ai >/dev/null 2>&1
sleep 2
final=$($COMPOSE exec -T bff python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())")
echo "$final" | grep -q '"status":"ok"' && pass "stack fully healthy after restoration" || fail "restore: $final"

echo
printf '%s\n' "${RESULT[@]}"
