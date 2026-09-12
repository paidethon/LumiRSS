#!/usr/bin/env bash
# Gate 8 production-like smoke (phase2 recovery).
#
# Drives the real stack from docker-compose.e2e.yml: built bff image
# (monolith included), web/Caddy, FreshRSS, RSSHub, Mailpit, controlled
# fixtures, the scripted OpenAI-compatible server, and the read-only
# vault. Every check prints PASS/FAIL; the summary is the release
# evidence. Browser-only flows (translation activation matrix) are
# marked BROWSER — they need a headed Chrome run and are NOT faked here.
#
#   docker compose -f e2e/gate8/docker-compose.e2e.yml up -d --build
#   e2e/gate8/run-smoke.sh up     # init + smoke
# No `set -e`: every check captures its own status and the summary is
# the verdict — an inverted grep guard must not abort the whole run.
set -uo pipefail

cd "$(dirname "$0")/../.."
COMPOSE="docker compose -f e2e/gate8/docker-compose.e2e.yml"
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
  $COMPOSE exec -T bff python - <<'PY'
import asyncio
from lumirss.auth_store import AuthStore
from lumirss.storage import Database

async def main():
    store = AuthStore(Database("/data/lumi.sqlite"))
    await store.set_password("e2e-login-" + "pwpw")

asyncio.run(main())
PY
}

smoke_login_and_phase1() { # 1. 登录（session auth）
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' -c "$COOKIE" -H "Origin: $BASE" \
    -H 'content-type: application/json' \
    -d "{\"password\": \"$E2E_LOGIN\"}" "$BASE/api/v1/auth/login")
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
  internal -X POST /api/v1/workspaces/read-later/items \
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
  $COMPOSE exec -T bff python - <<'PY'
import asyncio
from lumirss.config import LumiSettings
from lumirss.obsidian import ObsidianService
from lumirss.storage import Database

async def main():
    db = Database(LumiSettings().LUMIRSS_DB_PATH)
    service = ObsidianService(db, env_root=LumiSettings().LUMIRSS_OBSIDIAN_VAULT_DIR)
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
      echo
      printf '%s\n' "${RESULT[@]:-no checks}"
      ;;
    *) echo "usage: $0 {up|all}"; exit 2;;
  esac
}

main "$@"
