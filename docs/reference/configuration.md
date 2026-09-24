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
| `LUMIRSS_AUTH_MODE` | `basic`（默认，历史行为：Caddy basic_auth）或 `session`（持久会话登录：bcrypt 密码 + 长效 Cookie，见下）。`./lumirss deploy --auth-mode=session` 自动写入 |
| `LUMIRSS_AUTH_USER` / `LUMIRSS_AUTH_HASH` | basic 模式的 Caddy basic_auth 边缘访问控制（单组共享凭据，历史兼容；账号级登录请用 session 模式）。bcrypt 哈希（不是明文密码），`$$` 转义。**两个要么都设要么都不设，只设一个容器拒绝启动**；都为空 = 无 auth（受信内网/已有外层认证）。session 模式下忽略 |
| `LUMIRSS_SESSION_MAX_AGE_DAYS` | `180`（天）。session 模式的绝对不活跃窗口；活跃使用会滑动续期（临近过期自动延长），经常使用基本不需要重新登录 |
| `LUMIRSS_SESSION_SECURE_COOKIES` | `1`。`__Host-` 前缀 + `Secure`（要求 HTTPS，所有生产部署都应保持 1）；仅纯 HTTP 本地调试才设 0（此时 cookie 名退化为 `lumirss_session`） |
| `LUMIRSS_TRUSTED_PROXY_NETWORKS` | （空）。登录失败限流的可信代理网段（逗号分隔 CIDR）。空 = loopback+私网+链路本地（本栈两级 Caddy 拓扑默认即可）。仅这些网段的直连 peer 采纳 `X-Forwarded-For` **最后一跳**做限流分桶，其余 peer 的 XFF 一律忽略（防伪造刷桶锁死登录） |
| `LUMIRSS_PUBLIC_ORIGIN` | （空）。CSRF Origin 校验的精确公共源（如 `https://rss.example.com`），供会改写 Host 头的反代使用；空 = 与转发的 Host 头比对（本栈两级 Caddy 都保留 Host，默认即可） |
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
| `LUMIRSS_DB_PATH` | `<services/bff>/data/lumi.sqlite` | Lumi 控制库（身份/会话/邀请/FreshRSS 池/审计）；首次使用时创建。每用户业务库在 `LUMIRSS_DATA_DIR/users/<uid>/lumi.sqlite`（见 [ADR 0005](../decisions/0005-invite-multi-account.md)）。生产 compose 固定为 `/data/lumi.sqlite`（lumi-data 卷），不走 `.env.prod` |
| `LUMIRSS_DATA_DIR` | `LUMIRSS_DB_PATH` 的父目录 | Lumi 运行时状态根：`users/<uid>/`（每用户业务库 + secrets）、`secrets.json`（0600）、本地备份 `backups/`、恢复暂存 `restore-staging/` |
| `FRESHRSS_DATA_DIR` | 空 | FreshRSS 数据目录的**只读**挂载路径，供一致性在线备份；空 = 完整备份不可用（开发态）。生产 compose 固定为 `/freshrss-data` |
| `LUMIRSS_SEARCH_SYNC_INTERVAL` | `60.0`（秒） | 搜索投影后台同步节奏；`0` 关闭后台同步（测试用）。机制见 [../explanation/search.md](../explanation/search.md) |
| `LUMIRSS_ATOM_BASE_URL` | 空 | API 来源 / 邮件桥生成的 Atom 相对路径对外解析基准（`GET /api/v1/sources` 返回的 `atomUrl` 用它拼绝对 URL）；空 = 返回相对路径 |
| `LUMIRSS_OBSIDIAN_VAULT_DIR` | 空 | Obsidian vault 的容器内挂载路径（只读）。生产 compose 经 `LUMIRSS_OBSIDIAN_VAULT_HOST_DIR` 绑定宿主目录；空 = Obsidian 投影关闭 |
| `LUMIRSS_OBSIDIAN_SCAN_INTERVAL` | 秒 | vault 增量扫描节奏（默认见 `config.py`；`0` 关闭后台扫描） |
| `LUMIRSS_RAG_INDEX_INTERVAL` | 秒 | RAG 语义索引增量收敛节奏；`0` 关闭（显式 rebuild 仍可用）。模型加载在显式启用后进行，空闲自动卸载 |
| `LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS` | 空 | 逗号分隔主机名 allow-list：名单内的私网主机可作为**来源 URL / AI·LibreTranslate base URL** 被服务端访问（容器内 RSSHub、自托管 AI 等）。仅跳过"公网地址拒绝"，取回仍逐跳解析、校验、按钉住 IP 直连 |
| `LUMIRSS_ACCESS_LOG` | `json` | BFF 访问日志：`json` = 每请求一行结构化 JSON（request_id/路由模板/status/duration_ms/服务端派生 actor）；`off` = 静默。脱敏边界：绝不记录 query string、请求体、header、凭据 |
| `LUMIRSS_INTERNAL_TOKEN` | 空 | 同上表（BFF 侧读取） |
| `AI_API_KEY` | 空 | 同上表（BFF 侧读取） |
| `LUMIRSS_VERSION` / `LUMIRSS_COMMIT` | — | 版本与 commit 溯源，由镜像构建注入（见下） |

## 部署 / compose 层

| 键 | 默认 | 说明 |
|---|---|---|
| `LUMIRSS_IMAGE_TAG` | `latest` | GHCR 镜像 tag（`ghcr.io/paidethon/lumirss-web` / `-bff`）。`./lumirss deploy` 会把它实际部署的值持久化进 `.env.prod`，`update` / `rollback` 复用同一不可变引用；显式环境变量仍优先生效 |
| `LUMIRSS_BUILD_COMMIT` | （空） | 部署/构建时注入的 git commit → Web `VITE_GIT_COMMIT` 与 BFF `LUMIRSS_COMMIT` 两个 build-arg，「关于」页与 `/api/v1/version` 展示，用于版本偏斜诊断 |
| `LUMIRSS_HTTP_PORT` / `LUMIRSS_HTTPS_PORT` | `80` / `443` | Caddy 发布到宿主的端口；与 `COMPOSE_PROJECT_NAME` 一起用于同机隔离测试（避免端口与卷冲突） |
| `LUMIRSS_EXTERNAL_CADDY` | （空） | `1` = 外部宿主反代模式：web 只发布 `127.0.0.1:LUMIRSS_UPSTREAM_PORT`（纯 HTTP、任意 Host，无 ACME/443），TLS 由宿主 Caddy/nginx 负责。`./lumirss deploy --external-caddy` 自动写入；见 [../how-to/deploy.md](../how-to/deploy.md) |
| `LUMIRSS_UPSTREAM_PORT` | `18080` | external 模式下 web 发布的 loopback 端口（`127.0.0.1:<port> -> 80`）。必须与宿主反代 upstream 一致；`./lumirss caddy-config` 按它渲染站点块 |
| `LUMIRSS_TRANSLATE_PORT` | `50050` | 可选 LibreTranslate fragment（`docker-compose.translate.yml`）发布的 loopback 端口（`127.0.0.1:<port> -> 5000`），仅宿主机验证用；BFF 经 compose 内网名 `http://lumirss-libretranslate:5000` 访问。按需启停（`./lumirss translate up\|stop\|status`），见 [../how-to/optional-services.md](../how-to/optional-services.md) |
| `COMPOSE_PROJECT_NAME` | `lumirss-prod` | compose 项目名（决定卷前缀） |
| `LUMIRSS_WEB_MEM_LIMIT` / `_RESERVATION` | `128m` / `64m` | web 容器内存 limit/reservation。`./lumirss deploy --low-memory` 写入低资源预设（96m/48m）；改完用 `./lumirss doctor` 验证无 OOMKilled |
| `LUMIRSS_BFF_MEM_LIMIT` / `_RESERVATION` | `512m` / `128m` | BFF 容器（low-memory 预设 256m/96m） |
| `LUMIRSS_FRESHRSS_MEM_LIMIT` / `_RESERVATION` | `512m` / `128m` | FreshRSS 容器（low-memory 预设 320m/96m） |
| `LUMIRSS_RSSHUB_MEM_LIMIT` / `_RESERVATION` | `1g` / `256m` | RSSHub 容器（low-memory 预设 448m/192m） |
| `LUMIRSS_RSSHUB_MEMORY_MAX` | `256`（MB） | RSSHub 进程内 memory cache 上限（与固定镜像默认一致；low-memory 预设 64——小规模自托管足够） |
| `LUMIRSS_RSSHUB_NODE_OPTIONS` | （空 = V8 默认） | RSSHub Node 堆上限（如 `--max-old-space-size=256`）。**容器 limit 必须明显高于 V8 堆**，给 native memory 留余量（low-memory 预设 = 256 堆 + 448 容器） |
| `LUMIRSS_BACKUP_DIR` | `./backups` | `./lumirss backup` 输出目录 |
| `LUMIRSS_BACKUP_IMAGE` | `alpine:3.20` | 卷备份用的临时容器镜像 |
| `LUMIRSS_DOMAIN` / `LUMIRSS_AUTH_USER` / `LUMIRSS_AUTH_HASH` / `LUMIRSS_AUTH_PASSWORD` / `LUMIRSS_UPSTREAM_PORT` | — | 仅 `./lumirss deploy` 的非交互覆盖（环境变量，非文件键） |

## 开发栈（services/bff/.env）

`FRESHRSS_BASE_URL`（默认 `http://127.0.0.1:8080`）、`FRESHRSS_USERNAME`、
`FRESHRSS_API_PASSWORD` 必填；`RSSHUB_*`、`AI_API_KEY`、`FRESHRSS_DATA_DIR`
（完整备份用，见 [../how-to/backup-restore.md](../how-to/backup-restore.md)）
可选。模板：`services/bff/.env.example`。

## 非配置项：注册策略

可选公开注册**刻意不是 env 键**：实例级开关 `allow_public_registration`
的唯一真源在控制库 `instance_settings` 表（迁移 0089），默认关闭，升级
与全新安装都不开放；由 admin 经 `GET/PUT
/api/v1/admin/registration-policy` 显式切换，变更落审计。见
[ADR 0006](../decisions/0006-public-registration.md)。
