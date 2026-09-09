# Configuration Reference

> 配置键的唯一权威参考。事实来源：`.env.prod.example`、
> `services/bff/src/lumirss/config.py`、`docker-compose.prod.yml`、
> `./lumirss` 脚本。

## 通用规则

- **`$` 必须写成 `$$`**：docker compose 会对 env 值做插值，bcrypt 哈希
  `$2b$12$…` 不转义会被静默破坏。例：`LUMIRSS_AUTH_HASH=$$2b$$12$$abcdef…`。
  生成哈希：`docker run --rm caddy:2-alpine caddy hash-password`。
- `.env.prod` 永不进 Git；`services/bff/.env`（开发）同理。
- BFF 的 FreshRSS/RSSHub 校验是惰性的（首次相关请求时），`/health/live`
  始终可用。

## .env.prod（生产栈，两个容器共用）

| 键 | 说明 |
|---|---|
| `LUMIRSS_AUTH_USER` / `LUMIRSS_AUTH_HASH` | Caddy basic_auth 单用户访问控制。bcrypt 哈希（不是明文密码），`$$` 转义。**两个要么都设要么都不设，只设一个容器拒绝启动**；都为空 = 无 auth（受信内网/已有外层认证） |
| `DOMAIN` | 公网站点地址。真实 FQDN → Caddy 自动 Let's Encrypt（80+443）；`localhost`/空 → 自签本地证书并强制 HTTPS；`http://:80` 形式 → 纯 HTTP（仅内网调试） |
| `FRESHRSS_BASE_URL` | BFF 访问 FreshRSS 的**内部**地址（默认 `http://freshrss:80`，Docker 服务名，永不是公网 URL） |
| `FRESHRSS_USERNAME` / `FRESHRSS_API_PASSWORD` | FreshRSS API 凭据（服务端秘密；API Password 在 FreshRSS 用户设置里生成） |
| `FRESHRSS_PUBLIC_URL` | 可选、浏览器可见的 FreshRSS Web UI 公开链接（高级逃生入口）。留空 = 隐藏链接。必须是绝对 http(s)、不得是 Docker 内部名、不得带凭据/query/fragment；**刻意不从 `FRESHRSS_BASE_URL` 派生** |
| `RSSHUB_BASE_URL` | BFF 访问 RSSHub 的内部地址（预览抓取用；默认 `http://rsshub:1200`） |
| `RSSHUB_FRESHRSS_BASE_URL` | FreshRSS 抓取 feed 用的 RSSHub 地址；留空回退 `RSSHUB_BASE_URL`。订阅 feedUrl 由它构造（同内网时与 BASE_URL 同值） |
| `AI_API_KEY` | 可选 OpenAI-compatible API key。仅服务端秘密：不入库、不进备份、不进浏览器；留空 = AI 未配置（诚实显示）。推荐改在浏览器「设置 → AI」填写（服务端 SecretsStore，0600）；env 仅作为默认配置路径的回退 |
| `LUMIRSS_INTERNAL_TOKEN` | 可选但推荐的 BFF 内部鉴权。设置后 BFF 拒绝无匹配 `X-Lumi-Token` 头的 `/api/*` 请求（401；`/health/*` 豁免）；Caddy 自动注入，浏览器无感。URL-safe 字符集，`openssl rand -base64 32` 生成。两个容器读同一份文件：要么都设要么都不设（只设 BFF 侧 = 全 401，只设 Caddy 侧 = 无效果）；留空 = 关闭 |

## BFF 运行时（`config.py`；生产 compose 固定注入的除外）

| 键 | 默认 | 说明 |
|---|---|---|
| `LUMIRSS_DB_PATH` | `<services/bff>/data/lumi.sqlite` | Lumi SQLite 文件；首次使用时创建。生产 compose 固定为 `/data/lumi.sqlite`（lumi-data 卷），不走 `.env.prod` |
| `LUMIRSS_DATA_DIR` | `LUMIRSS_DB_PATH` 的父目录 | Lumi 运行时状态根：`secrets.json`（0600）、本地备份 `backups/`、恢复暂存 `restore-staging/` |
| `FRESHRSS_DATA_DIR` | 空 | FreshRSS 数据目录的**只读**挂载路径，供一致性在线备份；空 = 完整备份不可用（开发态）。生产 compose 固定为 `/freshrss-data` |
| `LUMIRSS_SEARCH_SYNC_INTERVAL` | `60.0`（秒） | 搜索投影后台同步节奏；`0` 关闭后台同步（测试用）。机制见 [../explanation/search.md](../explanation/search.md) |
| `LUMIRSS_INTERNAL_TOKEN` | 空 | 同上表（BFF 侧读取） |
| `AI_API_KEY` | 空 | 同上表（BFF 侧读取） |
| `LUMIRSS_VERSION` / `LUMIRSS_COMMIT` | — | 版本与 commit 溯源，由镜像构建注入（见下） |

## 部署 / compose 层

| 键 | 默认 | 说明 |
|---|---|---|
| `LUMIRSS_IMAGE_TAG` | `latest` | GHCR 镜像 tag（`ghcr.io/paidethon/lumirss-web` / `-bff`） |
| `LUMIRSS_BUILD_COMMIT` | （空） | 部署/构建时注入的 git commit → Web `VITE_GIT_COMMIT` 与 BFF `LUMIRSS_COMMIT` 两个 build-arg，「关于」页与 `/api/v1/version` 展示，用于版本偏斜诊断 |
| `LUMIRSS_HTTP_PORT` / `LUMIRSS_HTTPS_PORT` | `80` / `443` | Caddy 发布到宿主的端口；与 `COMPOSE_PROJECT_NAME` 一起用于同机隔离测试（避免端口与卷冲突） |
| `COMPOSE_PROJECT_NAME` | `lumirss-prod` | compose 项目名（决定卷前缀） |
| `LUMIRSS_BACKUP_DIR` | `./backups` | `./lumirss backup` 输出目录 |
| `LUMIRSS_BACKUP_IMAGE` | `alpine:3.20` | 卷备份用的临时容器镜像 |
| `LUMIRSS_DOMAIN` / `LUMIRSS_AUTH_USER` / `LUMIRSS_AUTH_HASH` / `LUMIRSS_AUTH_PASSWORD` | — | 仅 `./lumirss deploy` 的非交互覆盖（环境变量，非文件键） |

## 开发栈（services/bff/.env）

`FRESHRSS_BASE_URL`（默认 `http://127.0.0.1:8080`）、`FRESHRSS_USERNAME`、
`FRESHRSS_API_PASSWORD` 必填；`RSSHUB_*`、`AI_API_KEY`、`FRESHRSS_DATA_DIR`
（完整备份用，见 [../how-to/backup-restore.md](../how-to/backup-restore.md)）
可选。模板：`services/bff/.env.example`。
