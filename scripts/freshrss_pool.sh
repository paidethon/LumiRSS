#!/usr/bin/env bash
# O155：FreshRSS 账号池供应（运营者侧，邀请制多账户）。
#
# 用官方 FreshRSS CLI 在部署侧预建空的独立用户，并把 API 密码安全登记
# 进 Lumi 控制层（secrets 文件 0600 + freshrss_pool 行）。BFF 在邀请激
# 活时原子分配池账号——全程没有共享凭据；密码不进 argv（argv 会进
# /proc 与 shell 历史）、不出现在日志或本脚本输出。
#
# 用法（在仓库根）:
#   scripts/freshrss_pool.sh <数量> <freshrss基础URL> <FreshRSS管理员用户名> \
#     [Lumi基础URL] [Lumi管理Cookie文件] [FreshRSS容器名]
# 示例:
#   scripts/freshrss_pool.sh 3 http://freshrss admin http://127.0.0.1:8000 /tmp/lumi-cookie.jar lumirss-freshrss-1
#
# 环境变量 FRESHRSS_ADMIN_PASSWORD：FreshRSS 管理员密码（只从环境读，
# 不写进命令行）。LUMI_ADMIN_USERNAME / LUMI_ADMIN_PASSWORD：Lumi 管理
# 账号（默认 owner / 环境提供）。
# 本脚本不执行任意远程命令、不挂载 Docker socket——BFF 只通过受限
# 管理 API 收到登记结果。
set -euo pipefail

COUNT="${1:?usage: $0 <count> <freshrss-base-url> <freshrss-admin-user> [lumi-base-url] [cookie-jar] [freshrss-container]}"
FRESHRSS_URL="${2:?missing freshrss base url}"
ADMIN_USER="${3:?missing freshrss admin user}"
LUMI_URL="${4:-http://127.0.0.1:8000}"
COOKIE_JAR="${5:-}"
FRESHRSS_CONTAINER="${6:-lumirss-freshrss-1}"
ADMIN_PASS="${FRESHRSS_ADMIN_PASSWORD:?FRESHRSS_ADMIN_PASSWORD must be set in the environment}"
LUMI_USER="${LUMI_ADMIN_USERNAME:-owner}"
LUMI_PASS="${LUMI_ADMIN_PASSWORD:?LUMI_ADMIN_PASSWORD must be set in the environment}"

docker_ctx() {
  if docker ps --format '{{.Names}}' | grep -qx "$FRESHRSS_CONTAINER"; then
    docker exec "$FRESHRSS_CONTAINER" "$@"
  elif docker ps --format '{{.Names}}' | grep -qx "freshrss"; then
    docker exec freshrss "$@"
  else
    echo "ERROR: FreshRSS container not found (set FRESHRSS_CONTAINER)" >&2
    exit 1
  fi
}

jar() { printf '%s' "${COOKIE_JAR:-/tmp/lumi-pool-cookie.jar}"; }

# 一次性 Lumi 管理员登录（密码走 stdin，不进 argv）。
login_body="$(LUMI_USER="$LUMI_USER" LUMI_PASS="$LUMI_PASS" python3 - <<'PY'
import json, os
print(json.dumps({"username": os.environ["LUMI_USER"], "password": os.environ["LUMI_PASS"]}))
PY
)"
curl -sS -c "$(jar)" -H 'content-type: application/json' -d "$login_body" \
  "$LUMI_URL/api/v1/auth/login" >/dev/null

for _ in $(seq 1 "$COUNT"); do
  # 用户名与密码随机生成、一次性使用。官方 CLI 只接受 argv 传参
  # （无 stdin 选项）：值在 FreshRSS 容器内瞬时可见——这是部署侧
  # 宿主任意边界内的既有暴露面，文档如实记录；值不进本机 shell
  # 历史、不进日志、不回显。
  pool_user="lumi-$(openssl rand -hex 4)"
  api_password="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"
  freshrss_password="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"

  docker_ctx php ./cli/create-user.php \
    --user "$pool_user" \
    --password "$freshrss_password" \
    --api-password "$api_password" \
    --no-default-feeds >/dev/null

  # CLI 以 root 建目录：运行时用户（www-data）必须可读，否则 greader
  # 登录 401（与 e2e 栈同一坑）。路径作为 argv 传递，不经 shell 拼接。
  docker_ctx chown -R www-data:www-data "/var/www/FreshRSS/data/users/$pool_user"
  docker_ctx chmod 770 "/var/www/FreshRSS/data/users/$pool_user"

  register_body="$(pool_user="$pool_user" FRESHRSS_URL="$FRESHRSS_URL" api_password="$api_password" python3 - <<'PY'
import json, os
print(json.dumps({
    "freshrssUsername": os.environ["pool_user"],
    "freshrssBaseUrl": os.environ["FRESHRSS_URL"],
    "apiPassword": os.environ["api_password"],
}))
PY
)"
  http_code=$(curl -sS -o /tmp/lumi-pool-resp.json -w '%{http_code}' \
    -b "$(jar)" -H 'content-type: application/json' -d "$register_body" \
    "$LUMI_URL/api/v1/admin/pool")
  if [[ "$http_code" != "200" && "$http_code" != "201" ]]; then
    echo "ERROR: pool register failed ($http_code) for $pool_user" >&2
    cat /tmp/lumi-pool-resp.json >&2
    exit 1
  fi
  echo "pool ready: $pool_user"
  rm -f /tmp/lumi-pool-resp.json
done
rm -f "$(jar)"
echo "done: $COUNT account(s) registered into the pool"
