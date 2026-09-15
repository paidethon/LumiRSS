#!/usr/bin/env bash
# Round 2 定向运行时探针：验证 Round 1 修复在真实 Gate 8 栈上的行为
# （login → inbox/registry/read-later/rag 逐项）。自清理：探针数据删除。
#
# 口令与 token 沿用 run-smoke.sh 的约定：环境变量可覆盖、运行时拼接、
# 一次性本地值——本脚本不持有任何真实凭据。
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

icurl() { # icurl <path> [curl-args...] — path 必须是第一个参数
  local path="$1"; shift
  curl -sS -b "$COOKIE" -H "X-Lumi-Token: $INTERNAL_TOKEN" -H "Origin: $BASE" "$@" "$BASE$path"
}

# login（session auth）
curl -sS -o /dev/null -c "$COOKIE" -H "Origin: $BASE" -H 'content-type: application/json' \
  -d "{\"password\": \"$E2E_LOGIN\"}" "$BASE/api/v1/auth/login"

# 探针 1：非 ASCII bearer → 404（修复前 TypeError→500，Q-P1-11）
src=$(icurl /api/v1/inbox/sources -X POST -H 'content-type: application/json' -d '{"name": "probe"}')
uuid=$(echo "$src" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("uuid",""))')
[[ -n "$uuid" ]] && pass "connector created ($uuid)" || fail "connector create: $src"

code=$(curl -sS -o /dev/null -w '%{http_code}' -b "$COOKIE" -X POST \
  -H 'authorization: Bearer caf%C3%A9' -H 'content-type: application/json' \
  -d '{"guid":"x","content":"y"}' "$BASE/api/v1/inbox/ingest/$uuid")
[[ "$code" == "404" ]] && pass "inbox wrong/non-ascii bearer -> 404 envelope (was 500)" || fail "non-ascii bearer got $code"

# 探针 2：inbox 推送 → 加入稍后读 → timeline 返回 resolved 卡片（Q-P1-05）
secret=$(echo "$src" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("secret",""))')
push=$(curl -sS -X POST -b "$COOKIE" -H "Origin: $BASE" -H "authorization: Bearer $secret" -H 'content-type: application/json' \
  -d '{"guid":"probe-rl-1","title":"稍后读探针条目","content":"probe body content","publishedAt":"2026-09-15T01:00:00+00:00"}' \
  "$BASE/api/v1/inbox/ingest/$uuid")
ref=$(echo "$push" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ref",""))')
[[ -n "$ref" ]] && pass "inbox push created ($ref)" || fail "inbox push: $push"
icurl /api/v1/workspaces/read-later/items -X POST -H 'content-type: application/json' -d "{\"itemRef\": \"$ref\"}" >/dev/null
row=$(icurl /api/v1/workspaces/read-later/timeline | REF="$ref" python3 -c '
import json,sys,os
want=os.environ["REF"]
d=json.load(sys.stdin)
m=[i for i in d["items"] if i["itemRef"]==want]
if not m:
    print("missing"); raise SystemExit
r=m[0]
if r["stale"]:
    print("stale"); raise SystemExit
v=r.get("resolved")
if v:
    print("resolved:" + v["title"] + ":" + v["kind"])
else:
    print("no-resolved-view")')
[[ "$row" == resolved:* ]] && pass "read-later timeline renders inbox item as resolved card ($row)" || fail "timeline row: $row"

# 探针 3：源注册表出现 inbox 行（Q-P1-06 后端面）
icurl /api/v1/sources | python3 -c 'import json,sys; d=json.load(sys.stdin); assert any(s["type"]=="inbox" for s in d["sources"]), d' \
  && pass "source registry contains inbox adapter" || fail "registry missing inbox"

# 探针 4：record_error 健康面——非法 url 推送后连接器变红（Q-P2-03）
curl -sS -o /dev/null -X POST -b "$COOKIE" -H "Origin: $BASE" -H "authorization: Bearer $secret" -H 'content-type: application/json' \
  -d '{"guid":"probe-bad","content":"x","url":"javascript:alert(1)"}' "$BASE/api/v1/inbox/ingest/$uuid"
lasterr=$(icurl /api/v1/inbox/sources | UUID="$uuid" python3 -c '
import json,sys,os
want=os.environ["UUID"]
d=json.load(sys.stdin)
s=[x for x in d if x["uuid"]==want][0]
print("red" if s["lastError"] else "green")')
[[ "$lasterr" == "red" ]] && pass "connector lastError recorded on bad payload" || fail "connector health still green"

# 探针 5：RAG 增量任务 rag_index_pass 在生产镜像内真实收敛（Q-P2-02）
icurl /api/v1/rag/enable -X POST >/dev/null 2>&1
icurl /api/v1/rag/rebuild -X POST >/dev/null 2>&1
out=$($COMPOSE exec -T bff python - <<'PY'
import asyncio
from lumirss.rag import RagService, rag_index_pass
from lumirss.storage import Database

async def main():
    db = Database("/data/lumi.sqlite")
    svc = RagService(db)
    report = await rag_index_pass(svc)
    status = await svc.status()
    print(f"indexed={report.get('indexed')} swept={report.get('swept')} chunks={status['chunks']}")
    svc.close()

asyncio.run(main())
PY
)
echo "$out"
echo "$out" | grep -qE "indexed=[0-9]+ swept=[0-9]+ chunks=[0-9]+" && pass "rag_index_pass converges in production image ($out)" || fail "rag pass: $out"

# 探针 6：RAG 检索端点在增量后正常服务（hybrid 契约、语义腿诚实）
hit=$(icurl '/api/v1/rag/search?q=%E6%8E%A2%E9%92%88&k=5' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["items"]), d["semanticUsed"])' 2>/dev/null)
[[ -n "$hit" ]] && pass "rag search serves hybrid results (items/semanticUsed=$hit)" || fail "rag search failed"

# 清理：删除连接器（级联条目+投影）、移除探针的 read-later 成员、关闭 RAG
icurl "/api/v1/inbox/sources/$uuid" -X DELETE >/dev/null
icurl /api/v1/workspaces/read-later/timeline | REF="$ref" python3 -c '
import json,sys,os
want=os.environ["REF"]
d=json.load(sys.stdin)
for i in d["items"]:
    if i["itemRef"]==want:
        print(i["itemRef"]); break' > /tmp/probe_member.txt
member=$(cat /tmp/probe_member.txt 2>/dev/null || true)
if [[ -n "$member" ]]; then
  encoded=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$member")
  icurl "/api/v1/workspaces/read-later/items/$encoded" -X DELETE >/dev/null 2>&1 || true
fi
icurl /api/v1/rag/disable -X POST >/dev/null 2>&1
rm -f /tmp/probe_member.txt "$COOKIE"

echo
printf '%s\n' "${RESULT[@]}"
