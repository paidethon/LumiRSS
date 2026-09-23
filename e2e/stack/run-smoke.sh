#!/usr/bin/env bash
# Production-like smoke (phase2 recovery gate; migrated from e2e/gate8/).
#
# Drives the real stack from docker-compose.e2e.yml: built bff image
# (monolith included), web/Caddy, FreshRSS, RSSHub, Mailpit, controlled
# fixtures, the scripted OpenAI-compatible server, and the read-only
# vault. Every check prints PASS/FAIL; the summary is the release
# evidence. Browser-only flows (translation activation matrix) are
# marked BROWSER — they need a headed Chrome run and are NOT faked here.
# Checks that need the EXTERNAL internet (RSSHub catalog routes fetch
# real upstream sites) SKIP with an honest label unless
# LUMIRSS_E2E_ALLOW_NETWORK=1; the RSSHub chain itself runs offline via
# the instance's deterministic built-in /test/1 route.
#
#   docker compose -f e2e/stack/docker-compose.e2e.yml up -d --build
#   e2e/stack/run-smoke.sh up     # init + smoke
# No `set -e`: every check captures its own status and the summary is
# the verdict — an inverted grep guard must not abort the whole run.
#
# Multi-account note: since the invite-based multi-account change, login
# is {username, password} against the control-plane AccountsStore (the
# legacy auth_password table no longer feeds login), and Obsidian
# projection tables live in the owner's per-user database
# (/data/users/<owner-id>/lumi.sqlite), not the control DB.
set -uo pipefail

cd "$(dirname "$0")/../.."
COMPOSE="docker compose -f e2e/stack/docker-compose.e2e.yml"
BASE=http://127.0.0.1:8088
BFF=http://lumirss-e2e-bff:8000
# Throwaway E2E-local login value for a hermetic local stack — composed
# at runtime, overridable from the environment, never a real secret.
E2E_LOGIN="${E2E_LOGIN:-e2e-login-pwpw}"
INTERNAL_TOKEN="${E2E_INTERNAL_TOKEN:-e2e-internal-token-0123456789abcdef}"
COOKIE=$(mktemp)
RESULT=()

pass() { RESULT+=("PASS $1"); echo "PASS  $1"; }
fail() { RESULT+=("FAIL $1"); echo "FAIL  $1"; }
skip() { RESULT+=("SKIP $1"); echo "SKIP  $1"; }
allow_network() { [[ "${LUMIRSS_E2E_ALLOW_NETWORK:-0}" == "1" ]]; }
check() { # check <name> <exit-status>
  if [[ "$2" == "0" ]]; then pass "$1"; else fail "$1"; fi
}

api() { # api <method> <path> [curl-args...] — authenticated session call
  local method="$1" path="$2"; shift 2
  curl -sS -X "$method" -b "$COOKIE" -H "Origin: $BASE" "$@" "$BASE$path"
}

internal() { # internal <path> [curl-args...] — session + token via Caddy
  local path="$1"; shift
  curl -sS -b "$COOKIE" -H "X-Lumi-Token: $INTERNAL_TOKEN" "$@" "$BASE$path"
}

seed_login_value() {
  # Set the owner's password through the control-plane AccountsStore —
  # the same store the login route verifies against. The owner row is
  # bootstrapped at BFF startup (owner migration); the password starts
  # unguessable, so the smoke seed installs the known E2E value here.
  $COMPOSE exec -T -e E2E_LOGIN="$E2E_LOGIN" bff python - <<'PY'
import asyncio
import os

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.storage import Database

async def main():
    store = AccountsStore(Database("/data/lumi.sqlite"))
    owner = next(u for u in await store.list_users() if u["role"] == "owner")
    await store.set_password_hash(owner["id"], hash_password(os.environ["E2E_LOGIN"]))

asyncio.run(main())
PY
}

smoke_login_and_phase1() { # 1. 登录（session auth，邀请制多账户契约）
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' -c "$COOKIE" -H "Origin: $BASE" \
    -H 'content-type: application/json' \
    -d "{\"username\": \"owner\", \"password\": \"$E2E_LOGIN\"}" "$BASE/api/v1/auth/login")
  [[ "$code" == "200" || "$code" == "204" ]]
  check "01 login (session auth)" $?
}

smoke_read_later_server_side() { # 2. read-later 服务端时间线
  # FreshRSS must actually fetch the subscribed feed, then the BFF
  # projection syncs it before the search below can find an entry.
  $COMPOSE exec -T freshrss php ./cli/actualize-user.php --user e2e >/dev/null 2>&1 || true
  sleep 6
  # The projection syncs on its own cadence — poll briefly for it.
  local ref=""
  for _ in 1 2 3 4; do
    ref=$(internal '/api/v1/search?q=sqlite-vec&limit=1' | python3 -c 'import json,sys; d=json.load(sys.stdin); r=(d.get("items") or [{}])[0].get("entryRef",""); print(r)' 2>/dev/null || true)
    [[ -n "$ref" ]] && break
    sleep 6
    $COMPOSE exec -T freshrss php ./cli/actualize-user.php --user e2e >/dev/null 2>&1 || true
  done
  ref=$(internal '/api/v1/search?q=sqlite-vec&limit=1' | python3 -c 'import json,sys; d=json.load(sys.stdin); r=(d.get("items") or [{}])[0].get("entryRef",""); print(r)' 2>/dev/null || true)
  if [[ -z "$ref" ]]; then
    fail "02 read-later timeline (no rss entry available to save)"; return
  fi
  ref="rss:$ref"
  # internal() takes <path> FIRST — the historical `internal -X POST …`
  # order curled a garbage URL (silent stderr noise) and the count below
  # only passed on stale volume data.
  internal /api/v1/workspaces/read-later/items -X POST \
    -H 'content-type: application/json' -d "{\"itemRef\": \"$ref\"}" >/dev/null
  local count
  count=$(internal '/api/v1/workspaces/read-later/timeline?limit=50' | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["items"]))')
  [[ "$count" -ge 1 ]]
  check "02 read-later server-side timeline contains member" $?
}

smoke_mixed_workspace() { # 3. 混合 workspace（find-or-create：重跑容忍）
  api POST /api/v1/workspaces -H 'content-type: application/json' -d '{"name": "e2e-mixed"}' >/dev/null 2>&1
  local ws_id
  ws_id=$(api GET /api/v1/workspaces | python3 -c 'import json,sys; print(next(w["id"] for w in json.load(sys.stdin)["items"] if w["name"]=="e2e-mixed"))')
  local bookmark
  bookmark=$(api POST /api/v1/library/bookmarks -H 'content-type: application/json' \
    -d '{"url": "https://fixtures/sample-bookmark", "title": "e2e bookmark"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["ref"])')
  api POST "/api/v1/workspaces/$ws_id/items" -H 'content-type: application/json' -d "{\"itemRef\": \"$bookmark\"}" >/dev/null
  local kinds
  kinds=$(api GET "/api/v1/workspaces/$ws_id/contents" | python3 -c 'import json,sys; print(",".join(i["kind"] for i in json.load(sys.stdin)["items"]))')
  echo "$kinds" | grep -q "bookmark"
  check "03 workspace holds a bookmark kind (clip/snapshot/obsidian join later checks)" $?
}

smoke_clip_pipeline() { # 4. 剪藏服务端提取 + 恶意 HTML 清理
  local fetched
  fetched=$(api POST /api/v1/library/clips/fetch -H 'content-type: application/json' \
    -d '{"url": "http://fixtures/malicious.html"}')
  echo "$fetched" | grep -q 'should-never-survive' && { fail "04 clip fetch leaks script"; return; }
  echo "$fetched" | grep -q 'onerror\|onclick\|javascript:' && { fail "04 clip fetch leaks handlers"; return; }
  echo "$fetched" | grep -q '受控剪藏正文' || { fail "04 clip fetch lost the article body"; return; }
  local created
  created=$(api POST /api/v1/library/clips -H 'content-type: application/json' \
    -d '{"url": "http://fixtures/malicious.html"}')
  echo "$created" | grep -q 'should-never-survive' && { fail "04 stored clip leaks script"; return; }
  echo "$created" | grep -q '受控剪藏正文'
  check "04 clip created from server-extracted article (malice stripped)" $?
}

smoke_snapshot_offline() { # 5. snapshot 生产镜像创建 + 离线内容
  local created
  created=$(api POST /api/v1/library/snapshots -H 'content-type: application/json' \
    -d '{"url": "http://fixtures/malicious.html"}')
  echo "$created" | grep -q '"uuid"' || { fail "05 snapshot creation in prod image"; return; }
  $COMPOSE exec -T bff grep -rq '受控剪藏正文' /data/library/assets
  check "05 snapshot artifact exists in the production image data dir" $?
}

smoke_feeds_via_caddy() { # 6. 浏览器经 Caddy 访问 /feeds/*
  local body
  body=$(curl -sS "$BASE/feeds/does-not-exist.atom" || true)
  [[ -n "$body" ]] && ! echo "$body" | grep -q '<div id="root">'
  check "06 /feeds/* proxied through Caddy (not SPA fallback)" $?
}

smoke_freshrss_subscription() { # 7. FreshRSS 订阅 API Source 并抓到 entry
  local run_id src
  run_id="$(date +%s)"
  src=$(api POST /api/v1/api-sources -H 'content-type: application/json' -d '{
    "name": "e2e-json-'"$run_id"'",
    "endpoint": "http://fixtures/sample.json",
    "itemsExpr": "items",
    "fieldMap": {"id": "url", "title": "title", "url": "url", "published": "published", "body": "summary"},
    "subscribe": true
  }')
  echo "$src" | grep -q 'subscribeFailed' && { fail "07 API source subscribe failed"; return; }
  local atom_path
  atom_path=$(echo "$src" | python3 -c 'import json,sys; print(json.load(sys.stdin)["atomPath"])')
  $COMPOSE exec -T freshrss php -r 'echo @file_get_contents($argv[1]);' "http://bff:8000$atom_path" | grep -q 'sqlite-vec'
  check "07 freshrss container fetches the generated atom (entry present)" $?
}

smoke_etag_stale() { # 8. 稳定 ETag/304
  local run_id src atom_path etag code
  run_id="$(date +%s)"
  src=$(api POST /api/v1/api-sources -H 'content-type: application/json' -d '{
    "name": "e2e-etag-'"$run_id"'",
    "endpoint": "http://fixtures/sample.json",
    "itemsExpr": "items",
    "fieldMap": {"id": "url", "title": "title", "url": "url", "published": "published", "body": "summary"},
    "subscribe": false
  }')
  atom_path=$(echo "$src" | python3 -c 'import json,sys; print(json.load(sys.stdin)["atomPath"])')
  etag=$(internal "$atom_path" -D - -o /dev/null | grep -i '^etag:' | tr -d '\r' | awk '{print $2}')
  [[ -n "$etag" ]] || { fail "08 no etag"; return; }
  code=$(curl -sS -o /dev/null -w '%{http_code}' -H "If-None-Match: $etag" "$BASE$atom_path")
  [[ "$code" == "304" ]]
  check "08 stable etag + reliable 304" $?
}

smoke_webhook_bearer() { # 9. session auth 下 mail webhook 通路
  local run_id list path secret wrong
  run_id="$(date +%s)"
  # The bridge caps at 20 lists — sweep older E2E lists before creating.
  local old
  for old in $(api GET /api/v1/mail/bridge-lists | python3 -c 'import json,sys
for item in json.load(sys.stdin)["items"]:
    if item["name"].startswith("e2e-list-"):
        print(item["uuid"])' 2>/dev/null); do
    api DELETE "/api/v1/mail/bridge-lists/$old" >/dev/null 2>&1 || true
  done
  list=$(api POST /api/v1/mail/bridge-lists -H 'content-type: application/json' \
    -d "{\"name\": \"e2e-list-$run_id\"}")
  path=$(echo "$list" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("atomPath") or "")')
  secret=$(echo "$list" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("secret") or "")')
  # A bearer-bearing ingest is deferred past the session gate: a wrong
  # secret must reach the ROUTE auth (never the session middleware), so
  # anything except the session 401 proves the machine path exists.
  wrong=$(curl -sS -o /dev/null -w '%{http_code}' -X POST -b "$COOKIE" \
    -H 'authorization: Bearer totally-wrong' -H 'content-type: message/rfc822' \
    --data-binary $'From: a@b.c\nSubject: x\n\nbody' \
    "$BASE/api/mail/ingest/00000000-0000-0000-0000-000000000000")
  [[ "$wrong" != "401" ]] || { fail "09 webhook still session-blocked"; return; }
  if [[ -n "$path" && -n "$secret" ]]; then
    # The REAL relay flow: correct bearer delivers the message.
    local list_uuid ingest
    list_uuid=$(echo "$list" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("uuid") or "")')
    ingest=$(curl -sS -X POST -b "$COOKIE" -H "Origin: $BASE" \
      -H "authorization: Bearer $secret" -H 'content-type: message/rfc822' \
      --data-binary $'From: digest@list.example\r\nSubject: E2E newsletter issue\r\n\r\nHello E2E body' \
      "$BASE/api/mail/ingest/$list_uuid")
    echo "$ingest" | grep -q '"status"' || { fail "09 correct bearer refused: $ingest"; return; }
    $COMPOSE exec -T freshrss php -r 'echo @file_get_contents($argv[1]);' "http://bff:8000$path" | grep -q '<feed'
    check "09 webhook bearer path exists + mail atom reachable" $?
  else
    fail "09 mail list missing atomPath"
  fi
}

smoke_digest_mailpit() { # 10. 空摘要必须拒绝（不再发空邮件）
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST -b "$COOKIE" \
    -H "Origin: $BASE" -H 'content-type: application/json' -d '{}' \
    "$BASE/api/v1/digest/send-now")
  [[ "$code" == "422" ]]
  check "10 empty digest send-now refused (no empty emails)" $?
}

smoke_obsidian() { # 11. Obsidian bind mount + 同内容双文件
  internal /api/v1/obsidian/status | grep -q '"envRootConfigured":true' || { fail "11 env vault root not active"; return; }
  # The projection tables live in the OWNER's per-user database
  # (/data/users/<owner-id>/lumi.sqlite) — resolve the owner id from
  # the control-plane AccountsStore first, then open that file.
  $COMPOSE exec -T bff python - <<'PY'
import asyncio

from lumirss.accounts_store import AccountsStore
from lumirss.config import LumiSettings
from lumirss.obsidian import ObsidianService
from lumirss.storage import Database

async def main():
    settings = LumiSettings()
    accounts = AccountsStore(Database(settings.LUMIRSS_DB_PATH))
    owner = next(u for u in await accounts.list_users() if u["role"] == "owner")
    user_db = Database(f"{settings.LUMIRSS_DATA_DIR}/users/{owner['id']}/lumi.sqlite")
    service = ObsidianService(user_db, env_root=settings.LUMIRSS_OBSIDIAN_VAULT_DIR)
    report = await service.rescan()
    # Re-run tolerant: the first scan adds 4; later scans converge with
    # nothing removed — the duplicate-content copy must NEVER steal the
    # original's identity (P0-09g).
    assert report["removed"] == 0, report
    notes = await service.list_notes()
    assert len(notes) == 4, notes
    paths = {n["relPath"] for n in notes}
    assert "AI/transformer.md" in paths and "AI/transformer-副本.md" in paths, paths
    assert len({n["ref"] for n in notes}) == 4, "identity collapse!"

asyncio.run(main())
PY
  check "11 obsidian projection: duplicate content = two notes, mount active" $?
}

smoke_rag_honest() { # 12. RAG 能力状态诚实（向量证明依赖模型下载）
  internal /api/v1/rag/status | grep -qE 'enabled|model|available|chunks'
  check "12 rag status endpoint honest (vec hit proof in unit/e2e-ext)" $?
}

smoke_agent_thread() { # 13. provider 配置 + agent 线程
  local thread
  thread=$(api POST /api/v1/agent/threads -H 'content-type: application/json' -d '{"title": "e2e"}' 2>/dev/null || true)
  echo "$thread" | grep -q '"id"'
  check "13 agent thread created over the scripted provider stack" $?
}

smoke_tags_favorites() { # 14. tag 幂等
  local bookmark count
  bookmark=$(api POST /api/v1/library/bookmarks -H 'content-type: application/json' \
    -d '{"url": "https://fixtures/tagged", "title": "tagged"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["ref"])')
  api POST /api/v1/tags/assign -H 'content-type: application/json' \
    -d "{\"itemRef\": \"$bookmark\", \"name\": \"e2e-tag\"}" >/dev/null
  api POST /api/v1/tags/assign -H 'content-type: application/json' \
    -d "{\"itemRef\": \"$bookmark\", \"name\": \"e2e-tag\"}" >/dev/null
  count=$(internal /api/v1/tags | python3 -c 'import json,sys; print(sum(1 for t in json.load(sys.stdin)["items"] if t["name"]=="e2e-tag"))')
  [[ "$count" == "1" ]]
  check "14 tag attach idempotent (one tag row)" $?
}

smoke_backup() { # 17. backup 作业被接受（restore 演练见 gate 报告）
  local job
  job=$(api POST /api/v1/backups -H 'content-type: application/json' -d '{"target": "local"}' \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("jobId") or d.get("id") or "")' 2>/dev/null || true)
  [[ -n "$job" ]]
  check "17 backup job accepted (restore rehearsal in gate report)" $?
}

# --- P08: RSSHub → FreshRSS → per-user entries chain (18–24) ---------------
# The instance is the pinned diygod/rsshub container; the BFF previews via
# RSSHUB_BASE_URL and builds subscription feedUrls from
# RSSHUB_FRESHRSS_BASE_URL (both http://rsshub:1200 on this network). The
# two externally-networked checks (21/23) SKIP without
# LUMIRSS_E2E_ALLOW_NETWORK=1; everything else is fully offline.

smoke_rsshub_health() { # 18. rsshub /healthz（宿主侧有界等待）
  local port="${E2E_RSSHUB_HOST_PORT:-12001}" code=""
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
      "http://127.0.0.1:$port/healthz" 2>/dev/null || true)
    [[ "$code" == "200" ]] && break
    sleep 3
  done
  [[ "$code" == "200" ]] || { fail "18 rsshub /healthz never answered 200 on 127.0.0.1:$port (last: '${code:-none}')"; return; }
  pass "18 rsshub /healthz up and reachable from the test host (127.0.0.1:$port)"
}

smoke_rsshub_freshrss_dns() { # 19. freshrss 容器按服务名 DNS 抵达 rsshub
  # Bounded (5s stream timeout) — proves the freshrss container resolves
  # the compose service name AND gets a healthy answer, the exact view
  # it needs to fetch RSSHub feeds after subscribe.
  $COMPOSE exec -T freshrss php -r '
$c = stream_context_create(["http" => ["timeout" => 5]]);
$b = @file_get_contents("http://rsshub:1200/healthz", false, $c);
echo ($b === false) ? "unreachable" : "healthy:" . trim($b);
' | grep -q '^healthy:ok$'
  check "19 freshrss reaches rsshub over compose service DNS" $?
}

smoke_rsshub_catalog() { # 20. BFF 目录端点：configured + ≥1 路由
  api GET /api/v1/rsshub/routes | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["configured"] is True, d
assert len(d["routes"]) >= 1, d
'
  check "20 BFF rsshub catalog configured with >=1 route" $?
}

smoke_rsshub_preview() { # 21. BFF 预览目录路由（readhub 需外网 → 守卫）
  allow_network || { skip "21 BFF preview of a catalog route (needs external internet; set LUMIRSS_E2E_ALLOW_NETWORK=1)"; return; }
  local feed_url
  feed_url=$(api POST /api/v1/rsshub/preview -H 'content-type: application/json' \
    -d '{"routeId": "readhub", "params": {}}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("feedUrl", ""))' 2>/dev/null || true)
  # Exact equality proves the RSSHUB_FRESHRSS_BASE_URL wiring: the
  # subscription URL must be the freshrss-facing service-name base.
  [[ "$feed_url" == "http://rsshub:1200/readhub" ]]
  check "21 BFF preview builds the freshrss-facing rsshub feedUrl" $?
}

smoke_rsshub_chain() { # 22. 订阅 → freshrss 实抓 → per-user entries（离线确定性）
  # /test/1 is RSSHub's built-in deterministic route (no external
  # internet): five fixed items titled Title1..Title5. Subscribing to it
  # exercises the exact production path: POST /api/v1/subscriptions →
  # FreshRSS fetches http://rsshub:1200/test/1 itself → actualize → the
  # per-user GET /api/v1/entries timeline shows the entry.
  local feed='http://rsshub:1200/test/1' code found=""
  code=$(api POST /api/v1/subscriptions -o /dev/null -w '%{http_code}' \
    -H 'content-type: application/json' -d "{\"feedUrl\": \"$feed\"}")
  [[ "$code" == "201" || "$code" == "409" ]] || { fail "22 subscribe $feed refused (HTTP $code)"; return; }
  api GET /api/v1/subscriptions | python3 -c '
import json, sys
subs = json.load(sys.stdin)
assert any(s["feedUrl"] == "http://rsshub:1200/test/1" for s in subs), subs
' || { fail "22 rsshub subscription missing from GET /api/v1/subscriptions"; return; }
  for _ in 1 2 3 4; do
    $COMPOSE exec -T freshrss php ./cli/actualize-user.php --user e2e >/dev/null 2>&1 || true
    found=$(api GET /api/v1/entries -G \
      --data-urlencode "feedUrl=$feed" --data-urlencode "sourceType=rss" \
      | python3 -c 'import json,sys; items=json.load(sys.stdin)["items"]; print("yes" if any(i["title"] == "Title1" for i in items) else "no")' 2>/dev/null || true)
    [[ "$found" == "yes" ]] && break
    sleep 6
  done
  [[ "$found" == "yes" ]]
  check "22 rsshub subscribe -> freshrss fetch -> entries show deterministic Title1" $?
}

smoke_rsshub_preview_chain() { # 23. preview→订阅→抓取→entries 全链（需外网 → 守卫）
  allow_network || { skip "23 preview -> subscribe -> freshrss -> entries full chain (needs external internet; set LUMIRSS_E2E_ALLOW_NETWORK=1)"; return; }
  local feed_url code found=""
  feed_url=$(api POST /api/v1/rsshub/preview -H 'content-type: application/json' \
    -d '{"routeId": "readhub", "params": {}}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("feedUrl", ""))' 2>/dev/null || true)
  [[ -n "$feed_url" ]] || { fail "23 preview returned no feedUrl"; return; }
  code=$(api POST /api/v1/subscriptions -o /dev/null -w '%{http_code}' \
    -H 'content-type: application/json' -d "{\"feedUrl\": \"$feed_url\"}")
  [[ "$code" == "201" || "$code" == "409" ]] || { fail "23 subscribe $feed_url refused (HTTP $code)"; return; }
  for _ in 1 2 3 4; do
    $COMPOSE exec -T freshrss php ./cli/actualize-user.php --user e2e >/dev/null 2>&1 || true
    found=$(api GET /api/v1/entries -G --data-urlencode "feedUrl=$feed_url" \
      | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["items"]))' 2>/dev/null || true)
    [[ "${found:-0}" -ge 1 ]] && break
    sleep 6
  done
  [[ "${found:-0}" -ge 1 ]]
  check "23 preview feedUrl subscribed and freshrss fetched >=1 entry" $?
}

smoke_rsshub_dead_base() { # 24. 负向：死端点 → 稳定 502 rsshub_fetch_error
  # E2E-only preview baseUrl override (gated by LUMIRSS_E2E=1 in the BFF):
  # a dead port inside the compose must yield the STABLE error class as
  # JSON — never a 500 HTML page. One request, both code and body.
  local out code payload
  out=$(api POST /api/v1/rsshub/preview -w '\n%{http_code}' \
    -H 'content-type: application/json' \
    -d '{"routeId": "readhub", "params": {}, "baseUrl": "http://freshrss:9"}')
  code=$(echo "$out" | tail -n1)
  payload=$(echo "$out" | sed '$d')
  [[ "$code" == "502" ]] || { fail "24 dead rsshub base answered HTTP $code (want stable 502)"; return; }
  echo "$payload" | grep -q '"type":"rsshub_fetch_error"' || { fail "24 wrong error body: $payload"; return; }
  ! echo "$payload" | grep -qiE '<html|internal server error'
  check "24 dead rsshub endpoint -> stable 502 rsshub_fetch_error (JSON, never 500 HTML)" $?
}

main() {
  local what="${1:-all}"
  case "$what" in
    up)
      seed_login_value
      local installed
      installed=$($COMPOSE exec -T freshrss sh -c \
        'test -s /var/www/FreshRSS/data/config.php && echo yes || echo no')
      if [[ "$installed" != "yes" ]]; then
        $COMPOSE exec -T freshrss php ./cli/do-install.php \
          --default-user e2e --environment production --base-url http://freshrss \
          --language en --auth-type form --api-enabled --db-type sqlite
      fi
      $COMPOSE exec -T freshrss php ./cli/create-user.php \
        --user e2e --password e2e-api-pw-123456 --api-password e2e-api-pw-123456 \
        --no-default-feeds >/dev/null 2>&1 || true
      # CLI user creation runs as root: Apache (www-data) must be able to
      # read the user's config, or every greader login 401s with
      # "configuration cannot be found".
      $COMPOSE exec -T freshrss sh -c \
        'chown -R www-data:www-data /var/www/FreshRSS/data/users/e2e; chmod 770 /var/www/FreshRSS/data/users/e2e'
      # AI journeys 的 mock 跑在 runner 宿主机 18082：把 docker 网桥
      # 网关追加进 BFF 的私网白名单（环境变化时 compose 自动重建 bff）。
      local gateway
      gateway=$(docker network inspect lumirss-e2e_default \
        --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)
      if [[ -n "$gateway" ]]; then
        E2E_ALLOW_PRIVATE_HOSTS="fixtures,$gateway" $COMPOSE up -d --build bff >/dev/null 2>&1
      fi
      echo "init complete"
      ;;
    all)
      smoke_login_and_phase1
      # Subscription first: the read-later check needs projected entries.
      smoke_freshrss_subscription
      smoke_etag_stale
      smoke_read_later_server_side
      smoke_mixed_workspace
      smoke_clip_pipeline
      smoke_snapshot_offline
      smoke_feeds_via_caddy
      smoke_webhook_bearer
      smoke_digest_mailpit
      smoke_obsidian
      smoke_rag_honest
      smoke_agent_thread
      smoke_tags_favorites
      smoke_backup
      # P08: RSSHub chain — 21/23 SKIP without LUMIRSS_E2E_ALLOW_NETWORK=1.
      smoke_rsshub_health
      smoke_rsshub_freshrss_dns
      smoke_rsshub_catalog
      smoke_rsshub_preview
      smoke_rsshub_chain
      smoke_rsshub_preview_chain
      smoke_rsshub_dead_base
      echo
      printf '%s\n' "${RESULT[@]:-no checks}"
      ;;
    *) echo "usage: $0 {up|all}"; exit 2;;
  esac
}

main "$@"
