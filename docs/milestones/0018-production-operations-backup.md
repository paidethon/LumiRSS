# 0018 — Production, Operations & Backup

> Status: **In Progress** · Branch: `feat/0018-production-operations-backup`

## Why

LumiRSS 从 0001 到 0017 已是功能完整的单用户阅读器，但一直运行在「开发态」：
`docker-compose.yml` 只有 FreshRSS + RSSHub 两个裸容器，BFF 和 Web 由开发者本机
手动跑；没有生产部署拓扑、没有真实依赖诊断、没有灾难恢复备份。RSSHub 设置页
当前是浏览器本地 16 实例清单，会让用户误以为它在控制服务端 runtime。0018 让
LumiRSS 真正拥有**可部署、可诊断、可备份、可恢复**的生产基础，同时守住架构
边界（无 Docker socket、无 arbitrary env/shell、无 RSS shadow copy）。

## Goal

在**不破坏开发 compose、不破坏现有阅读链路**的前提下，交付四个边界清晰的部分：

```text
A. Production Deployment    — 生产拓扑 + Caddy + 持久卷 + healthcheck
B. RSSHub Control Center    — schema 驱动、allow-list、typed 的真实控制面
C. FreshRSS Operations      — 真实依赖状态 / readiness / 安全诊断
D. Backup / WebDAV / Restore — 灾难恢复备份 + 服务器端 WebDAV + 分阶段恢复
```

## User outcome

- 用户日常仍然只打开 LumiRSS 一个界面；
- 在「账户与服务」看到 FreshRSS / RSSHub / Backup 的**真实状态**（不是假指标）；
- 在 RSSHub 控制中心按分组编辑受控配置，明确知道「需要重启 RSSHub 生效」；
- 一键创建全量备份（Lumi DB 一致性快照 + FreshRSS 数据），上传 WebDAV，查看历史；
- 恢复前先预览 + 校验 + 生成当前状态安全备份，再显式确认，失败有恢复路径。

## Current baseline (verified 2026-09-04)

- FreshRSS `freshrss/freshrss:1.29.1`，数据在 `data/users/<user>/db.sqlite` +
  `data/config.php`；官方 CLI 提供 `db-backup.php`（SQLite 一致性备份）。
- RSSHub `diygod/rsshub@sha256:387fd32…`（git `86516b3`，`RSSHub/1.0`），
  `/healthz` 返回 `ok`；config 模块 env schema 已从容器内 dist 逆向确认。
- BFF：`services/bff`（FastAPI，480 tests pass）；`/health/live` 存在；
  `lumi.sqlite`（migrations 0001/0002）；AI 设置 + portable settings 均走
  `lumi_settings` KV；错误全部映射到稳定 `{error:{type,message}}`。
- Web：`apps/web`（522 tests pass）；设置中心有 RSSHub 实例清单（浏览器本地
  参考，非 runtime）、备份页（纯设置导出/导入）、「账户与服务」占位（plannedFor 0018）。
- 无 Dockerfile、无生产 compose、无 Caddy。

## Scope

1. Production Deployment：BFF image、Web 构建镜像（Caddy 静态 + /api 反代）、
   `docker-compose.prod.yml`、持久卷、healthcheck、restart policy、日志轮转、
   资源限制、`.env.prod.example`、单用户访问控制（Caddy Basic Auth，TLS 优先）。
2. Operations：`/health/ready`、`GET /api/v1/operations/status`、FreshRSS/RSSHub
   依赖探活、SQLite readiness、结构化日志 + 关联 ID + 延迟 + 错误分类 + 脱敏。
3. RSSHub Control Center：typed allow-list schema、desired/applied、restart-required、
   secret write-only、config 导出 helper、runtime 状态。
4. Backup：版本化 manifest、lumi.sqlite online backup、FreshRSS 数据一致性备份
   （只读挂载卷 + sqlite backup API，无 Docker socket）、SHA-256、backup job model
   （单并发、bounded）、local + WebDAV 目标。
5. WebDAV：服务器端 httpx WebDAV（MKCOL/PUT/GET/PROPFIND/DELETE）、secret 写只读、
   URL 策略、TLS 校验、测试连接。
6. Restore：分阶段状态机、校验、兼容性、预览、当前状态安全备份、显式确认、
   lumi 在线恢复 + FreshRSS 离线恢复、失败/恢复状态。
7. UI：Backup 页升级、Operations 页（账户与服务）、RSSHub Control Center、
   响应式 + 可访问性。
8. Security review + 全量回归 + 文档收口。

## Non-goals (unchanged boundaries)

- 0019 MVP Stabilization & Release 的全部内容；
- multi-user / OAuth / social / recommendation / native mobile / Obsidian /
  web clipping / email / vector DB / semantic search；
- Redis / Celery / n8n / Kubernetes / Prometheus / Grafana / Loki / OTel；
- arbitrary Docker admin / arbitrary shell / generic server dashboard /
  generic environment editor；
- S3 / OneDrive / Google Drive backup；
- AI 新功能、Reader 双栏、分页阅读、全局搜索；
- FreshRSS replacement、RSS data shadow copy；
- 不升级 FreshRSS / RSSHub 版本（pin 不变）。

## Architecture decisions

### AD-0018-1 — 生产拓扑：Caddy 统一入口，上游不暴露

```text
Internet / private access
        ↓
      Caddy (web 服务：静态 Web + /api 反代 + 单用户 Basic Auth)
     /     \
静态 Web   /api → BFF (uvicorn, 内部端口 8000)
                   ├─ FreshRSS (内部网络, 不暴露)
                   ├─ RSSHub   (内部网络, 不暴露)
                   └─ lumi-data volume (lumi.sqlite)
```

- `docker-compose.yml`（开发）保持不动。
- 新增 `docker-compose.prod.yml`：`web`（Caddy，`apps/web/Dockerfile`）、
  `bff`（`services/bff/Dockerfile`）、`freshrss`、`rsshub`（同 pin）。
- FreshRSS/RSSHub **无 ports 映射**（除 127.0.0.1 调试可选），只走内部网络。
- BFF 通过服务名 `http://freshrss:80` / `http://rsshub:1200` 访问上游。
- FreshRSS 数据卷以**只读**挂载进 BFF（`/freshrss-data:ro`），用于无 socket
  的一致性备份（AD-0018-5）。

### AD-0018-2 — 单用户访问控制：Caddy Basic Auth（默认 + 可选关闭）

- 默认访问模式 = **Caddy Basic Auth**：单一用户，bcrypt 哈希。
- `LUMIRSS_AUTH_USER` + `LUMIRSS_AUTH_HASH`（`caddy hash-password` 生成）在
  `.env.prod` 提供；两者都为空 → 不启用 auth（受信内网/反代后部署）。
- TLS：Caddyfile site address = `{$DOMAIN:localhost}`。设置真实域名 → Caddy
  自动 Let's Encrypt；`localhost` → 仅 HTTP（内网 smoke）。
- repo 只放占位 Caddyfile（`__AUTH_USER__` / `__AUTH_HASH__`），entrypoint
  脚本按 env 渲染；**绝不提交真实哈希**。密码不出现在 JS、URL、日志。

### AD-0018-3 — 依赖语义：失败隔离，非全挂

- `lumi.sqlite` 不可用 → readiness 失败（核心状态）。
- FreshRSS 不可用 → 阅读/订阅不可用（已有语义），BFF 仍活。
- RSSHub 不可用 → 已抓取的 RSS 阅读不受影响（只影响来源发现/预览），status
  如实报 `unavailable`，绝不把 RSSHub 视为核心依赖。
- `GET /health/ready` 只在核心依赖（SQLite + 配置）失败时 503。

### AD-0018-4 — RSSHub Control Center：staged desired/applied，无 socket

- Lumi 存储 **desired config**（typed allow-list JSON，`lumi_settings` KV
  `rsshub.desired`）与 **applied snapshot**（`rsshub.applied`，仅 operator
  确认时更新）。
- `restartRequired` = desired != applied（逐项 + 计数）。Lumi **永不**自行
  restart RSSHub（不给 BFF Docker socket）。
- 生效路径 = operator：Control Center 导出 `.env` 片段（非 secret 明文；secret
  只渲染 key 名 + 提示）→ 更新 compose env → 重启 → 点击「标记为已应用」。
- secret（ACCESS_KEY / 路由凭据 / PROXY_URI）write-only：`GET configured`、
  `PUT`、`DELETE`，永不明文回读，不进日志/截图/备份。

### AD-0018-5 — FreshRSS 一致性备份：只读卷 + SQLite online backup

- 生产 compose 将 `freshrss-data` 只读挂载进 BFF。
- 备份引擎对 `users/*/db.sqlite` 使用 Python `sqlite3.Connection.backup()`
  （SQLite 官方 online backup，等价于 FreshRSS `db-backup.php` 的 `dbCopy`），
  对 `config.php` 等非 DB 文件逐字节复制。**绝不 cp 运行中的 db**。
- 若 FreshRSS 数据目录不可用（开发态/未挂载）→ 全量备份报
  `freshrss_data_unavailable`（诚实失败，不产半成品）。

### AD-0018-6 — 秘密存储：secrets.json（0600），永不进 SQLite / 备份

- RSSHub route credentials、WebDAV password 存 `data/secrets.json`（`chmod 600`，
  gitignored）。AI_API_KEY / FreshRSS 密码保持 env-only。
- 秘密**永不进 lumi.sqlite**，因此 lumi.sqlite 的全量备份天然不含秘密；
  manifest 只写 `excludedSecret: configured`。
- 恢复后要求重新配置秘密（manifest 声明）。

### AD-0018-7 — Backup job：单并发、bounded、重启可恢复

- `backup_jobs` 表（id/type/status/stage/createdAt/startedAt/finishedAt/
  target/summary/safe_error）。status ∈ queued/running/succeeded/failed。
- 进程内 `asyncio.Lock` + DB 守卫：同一时间最多一个 running job；destructive
  restore 与 full backup 互斥。
- 后台 `asyncio.create_task`（引用挂在 app.state）；BFF 重启时把残留 `running`
  标记为 `interrupted`（不假装仍在运行）。
- 无真实进度百分比 → 只展示 stage（不伪造 73%）。

### AD-0018-8 — Backup 格式：ZIP + versioned manifest + SHA-256

- 文件：`lumirss-<UTC 紧凑时间戳>.backup`（ZIP，`ZIP_DEFLATED`）。
- 根含 `manifest.json`（backupSchemaVersion=1）+ `lumi.sqlite`（online backup）
  + `freshrss-data/…`（相对路径保持）+ 每文件 SHA-256。
- 恢复前**先校验 checksum 再解包**；tampered/truncated 拒绝。

### AD-0018-9 — Restore 状态机（分阶段）

```text
select → download → checksum → manifest → compatibility → preview
→ safety backup(current) → explicit confirm("RESTORE") → restore
→ reload/offline note → health validation → success/recovery
```

- lumi.sqlite：在线恢复（safety backup 先行 → backup API 原地恢复 →
  `PRAGMA integrity_check` → 重置迁移缓存）。
- FreshRSS 数据：**离线恢复**——校验后 staged 到 `restore-ready/freshrss/`，
  UI 明确「Ready for offline restore」+ 官方 `docker compose` 步骤；Lumi
  绝不写运行中的 FreshRSS 卷。
- 失败：保留 failure stage、保留 safety backup、不删原备份、给出安全 recovery
  信息（无 stacktrace/凭据）。

### AD-0018-10 — WebDAV：httpx 轻量实现 + 服务器端代理

- 仅 httpx：`MKCOL` / `PUT` / `GET` / `PROPFIND`(depth 1) / `DELETE`（仅 backup
  根目录内）。有界超时/响应大小/XML（defusedxml）。
- URL 策略：绝对 http(s)，拒绝 credentials-in-URL、危险 scheme；默认 `https` +
  TLS 校验（`tlsVerify` 可显式关闭，供自签名）；redirect 有界且必须同 origin。
  http 仅允许 loopback/私网（trusted operator config，与 untrusted source URL
  语义分离）。
- 浏览器永不直连 WebDAV（`/api/v1/backups/webdav/*` 全走 BFF）。
- 远程目录布局：`<remoteDir>/LumiRSS/backups/<YYYY>/<MM>/lumirss-….backup`。

## Security model

- **无 Docker socket**：正常 BFF 永不挂 `/var/run/docker.sock`；restart/restore
  用 operator 官方 compose 路径。
- **上游不暴露**：FreshRSS/RSSHub 无公网端口。
- **秘密边界**：无 Git / 无 localStorage / 无 API echo / 无日志 / 无截图 /
  无 manifest 明文 / 无未加密备份。
- **URL/SSRF**：WebDAV 为 operator-trusted 配置（结构校验 + 同源 redirect +
  私网显式允许）；来源发现/RSSHub 预览维持既有 untrusted 语义。
- **Archive**：拒绝 `../`、绝对路径、symlink、重复名覆盖、zip bomb（成员数量/
  大小上限 + 解压总量上限）。
- **Restore**：显式确认（输入 `RESTORE`）、当前状态安全备份、互斥锁、兼容性
  检查、失败恢复路径。
- **RSSHub**：typed allow-list，无任意 env、无任意 shell、无 secret 回读。

## Backup format (manifest v1)

```json
{
  "backupSchemaVersion": 1,
  "appName": "LumiRSS",
  "createdAt": "<ISO8601 UTC>",
  "lumiVersion": "0.1.0",
  "lumiDbSchemaVersion": 3,
  "components": ["lumi.sqlite", "freshrss-data"],
  "secretPolicy": {
    "excludedSecrets": ["ai.api_key", "freshrss.api_password",
      "rsshub.route_credentials", "rsshub.access_key", "webdav.password",
      "auth.password"],
    "configured": true
  },
  "files": [
    {"path": "lumi.sqlite", "size": 123, "sha256": "…"},
    {"path": "freshrss-data/config.php", "size": 456, "sha256": "…"}
  ]
}
```

## API contracts

```text
GET    /health/ready
GET    /api/v1/operations/status

GET    /api/v1/rsshub/config
PATCH  /api/v1/rsshub/config
GET    /api/v1/rsshub/config/export            (text/plain env 片段)
PUT    /api/v1/rsshub/config/secrets/{key}
DELETE /api/v1/rsshub/config/secrets/{key}
POST   /api/v1/rsshub/config/apply             (operator 标记已应用)

GET    /api/v1/backups/webdav                  (redacted 设置)
PUT    /api/v1/backups/webdav                  (password 写只读语义)
POST   /api/v1/backups/webdav/test
GET    /api/v1/backups                         (job 历史)
POST   /api/v1/backups                         (创建 full backup job → 202)
GET    /api/v1/backups/{id}                    (job 详情/stage)
GET    /api/v1/backups/remote                  (WebDAV 远端备份列表)
POST   /api/v1/restore/preview                 (校验 + 预览 → restoreSessionId)
POST   /api/v1/restore                         (确认 "RESTORE" 执行)
```

错误全部走既有 `{error:{type,message}}` 信封（新增稳定类型：`backup_busy` /
`backup_not_found` / `backup_invalid` / `backup_checksum_mismatch` /
`backup_unsupported_version` / `backup_restore_confirmation_required` /
`backup_restore_preview_required` / `backup_freshrss_unavailable` /
`webdav_not_configured` / `webdav_error` / `rsshub_unknown_key` /
`rsshub_invalid_value` / `rsshub_secret_not_found`）。

## RSSHub config schema（pinned 86516b3 已核验）

| key | group | type | default | secret | editable | restart |
|---|---|---|---|---|---|---|
| PORT | Instance | int | 1200 | no | no（信息项） | yes |
| LISTEN_INADDR_ANY | Instance | bool | true | no | yes | yes |
| DISABLE_IPV6 | Instance | bool | false | no | yes | yes |
| CACHE_TYPE | Cache | enum(memory/redis) | memory | no | yes | yes |
| CACHE_EXPIRE | Cache | int(分钟) | 300 | no | yes | yes |
| CACHE_CONTENT_EXPIRE | Cache | int(分钟) | 3600 | no | yes | yes |
| CACHE_REQUEST_TIMEOUT | Cache | int(秒) | 60 | no | yes | yes |
| MEMORY_MAX | Cache | int(MB) | 256 | no | yes | yes |
| REQUEST_TIMEOUT | Network | int(ms) | 30000 | no | yes | yes |
| UA | Network | string | "" | no | yes | yes |
| ALLOW_ORIGIN | Network | string | "" | no | yes | yes |
| DISALLOW_ROBOT | Network | bool | false | no | yes | yes |
| PROXY_URI | Network | string | "" | **yes** | yes | yes |
| ACCESS_KEY | Access Control | string | "" | **yes** | yes | yes |
| ALLOW_USER_HOTLINK_TEMPLATE | Access Control | bool | false | no | yes | yes |
| HOTLINK_TEMPLATE | Access Control | string | "" | no | yes | yes |
| ALLOW_USER_SUPPLY_UNSAFE_DOMAIN | Access Control | bool | false | no | yes | yes |
| PUPPETEER_WS_ENDPOINT | Browser Runtime | string | "" | no | yes | yes |
| CHROMIUM_EXECUTABLE_PATH | Browser Runtime | string | "" | no | yes | yes |
| ENABLE_REMOTE_DEBUGGING | Browser Runtime | bool | false | no | yes | yes |
| DEBUG_INFO | Advanced | bool | true | no | yes | yes |
| LOGGER_LEVEL | Advanced | enum | info | no | yes | yes |
| NO_LOGFILES | Advanced | bool | false | no | yes | yes |
| ENABLE_CLUSTER | Advanced | bool | false | no | yes | yes |
| TITLE_LENGTH_LIMIT | Advanced | int | 150 | no | yes | yes |
| GITHUB_ACCESS_TOKEN | Route Credentials | secret | "" | **yes** | yes | yes |
| ZHIHU_COOKIES | Route Credentials | secret | "" | **yes** | yes | yes |
| DOUBAN_COOKIE | Route Credentials | secret | "" | **yes** | yes | yes |
| WEIBO_COOKIES | Route Credentials | secret | "" | **yes** | yes | yes |
| YOUTUBE_KEY | Route Credentials | secret | "" | **yes** | yes | yes |
| XIAOHONGSHU_COOKIE | Route Credentials | secret | "" | **yes** | yes | yes |
| SSPAI_BEARERTOKEN | Route Credentials | secret | "" | **yes** | yes | yes |
| GITEE_ACCESS_TOKEN | Route Credentials | secret | "" | **yes** | yes | yes |

所有可编辑项 `restartRequired=true`（本版本无「即时生效」项——Lumi 无法在不
restart 的前提下安全注入 runtime env，故如实标记）。secret 项 API 只返回
`configured: true/false`，永不明文回读。

## Gate checklist

- [ ] G1 — Spec frozen（本文件）
- [ ] G2 — Production deployment foundation（compose/Dockerfile/Caddy/env/卷/健康）
- [ ] G3 — RSSHub Control Center（schema/desired-applied/secret/status）
- [ ] G4 — FreshRSS Operations（status/readiness/安全诊断）
- [ ] G5 — Lumi Backup Engine（manifest/online backup/job model）
- [ ] G6 — WebDAV（server-side client/settings/test）
- [ ] G7 — Restore state machine（preview/confirm/safety/offline）
- [ ] G8 — Backup UI（状态/手动/WebDAV/历史/配置迁移）
- [ ] G9 — Operations UI（账户与服务）
- [ ] G10 — Production security review（threat model）
- [ ] G11 — Full regression + Playwright + vision QA + docs

## Acceptance criteria

- Production：`docker compose -f docker-compose.prod.yml config` 通过；Web + BFF
  + FreshRSS + RSSHub 拓扑有效；Caddy 反代 /api；上游不暴露公网；持久卷齐全。
- Operations：`/health/ready` 与 `/api/v1/operations/status` 真实反映依赖，无
  假指标；RSSHub down 不影响已抓取阅读。
- RSSHub：schema 驱动 + allow-list + typed + secret 写只读 + restart 语义真实；
  无任意 env/shell、无 Docker socket。
- Backup：versioned manifest + lumi.sqlite 一致性备份 + FreshRSS 一致性备份 +
  SHA-256 + WebDAV 上传/列表 + 历史；无 secret 泄漏。
- Restore：下载/校验/兼容性/预览/安全备份/显式确认/隔离验证/健康检查/
  失败恢复。
- Quality：BFF 全量 pytest、Web 全量 vitest、lint、build、Playwright、
  production smoke、glm-5.3-flash visual QA（或诚实记录不可用）、无回归。

## Notes during execution

（执行过程中按需追加）
