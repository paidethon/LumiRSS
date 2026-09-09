# Operations Guide — LumiRSS 生产运维（0018/0019）

> 面向自托管 operator。对应实现：`docker-compose.prod.yml`、`services/bff`、
> `apps/web/Dockerfile`（Caddy + docker-entrypoint.sh）。

## 1. Production install

```bash
cp .env.prod.example .env.prod   # 填写真实值（见 §2）
docker compose -f docker-compose.prod.yml up -d --build

# 就绪检查：/health/* 只在 BFF 容器内暴露（Caddy 仅反代 /api/*，不代理
# /health/*），因此从容器内检查（与镜像 HEALTHCHECK 同一手法）：
docker compose -f docker-compose.prod.yml exec bff \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).status)"

# 公网入口（Caddy 发布的 80/443）自检：SPA 首页可返回；若 DOMAIN 强制
# HTTPS 则用 https://<DOMAIN>/（自签本地证书需 -k）。
curl -fsS -o /dev/null http://127.0.0.1/
```

- 唯一公网入口是 `web`（Caddy，80/443）；FreshRSS / RSSHub 只在内部网络。
- BFF **不发布任何宿主端口**：`/health/live`、`/health/ready` 只能容器内
  访问；外部监控走经反代的 `/api/v1/operations/status`（见 §4）。
- FreshRSS / RSSHub 镜像按 digest/版本 pin（不随系统升级漂移）。
- 最低资源：2 vCPU / 2 GB RAM / 10 GB 磁盘（RSSHub 峰值内存最高）。

## 2. 配置与秘密（.env.prod）

- **`$` 必须写成 `$$`**：docker compose 会对 env 值做插值，bcrypt 哈希
  `$2b$12$…` 不转义会被静默破坏（0018 实测确认）。例：
  `LUMIRSS_AUTH_HASH=$$2b$$12$$abcdef…`。
- 生成哈希：`docker run --rm caddy:2-alpine caddy hash-password`。
- 两个 auth 变量要么都设、要么都不设；**只设一个容器会拒绝启动**
  （防止半配置静默关闭访问控制）。
- `DOMAIN`：真实域名 → Caddy 自动 Let's Encrypt；`localhost` → 自签
  本地证书并强制 HTTPS；`http://:80` 形式 → 纯 HTTP（仅内网调试）。
- 秘密（`AI_API_KEY`、`FRESHRSS_API_PASSWORD`）只在服务端 env /
  secrets.json，永不进 Git、数据库、备份或浏览器。AI Key 也可以（且推荐）
  在浏览器「设置 → AI」中直接填写：写入服务端 SecretsStore（0600），
  env `AI_API_KEY` 仅作为默认配置路径的回退；已映射到某个启用的
  profile 的 purpose 必须使用该 profile 自己的 key（无 key 即诚实
  显示未配置，不回退 default/env key）。

## 3. Caddy auth / noauth

- 两者都设置 → 渲染 `Caddyfile.auth`（basic_auth，bcrypt）。
- 都为空 → `Caddyfile.noauth`（受信内网/已有外层认证）。
- 安全响应头（nosniff / DENY / no-referrer / HSTS / Permissions-Policy /
  CSP——见 §3.1）两种模式都启用。

### 3.1 BFF internal token（0021，可选但推荐）

`.env.prod` 设置 `LUMIRSS_INTERNAL_TOKEN`（URL-safe 字符集，如
`openssl rand -base64 32` 的输出）后：

- BFF 拒绝一切不带匹配 `X-Lumi-Token` 头的 `/api/*` 请求（401）；
  `/health/*` 豁免（容器 healthcheck 用）。
- Caddy 的 entrypoint 会渲染 `header_up X-Lumi-Token …`，因此浏览器
  正常使用不受影响；只有**绕过 Caddy 直连 BFF** 的内网调用被拒。
- 两个容器读同一份 `.env.prod`，一起设置即可；只设 BFF 侧会让所有
  API 变 401，只设 Caddy 侧无效果。留空（默认）= 关闭，行为与
  0021 之前一致（开发栈/E2E 不受影响）。

### 3.2 安全响应头与 CSP

- CSP：`script-src 'self'` + 内联主题脚本按 sha256 pin（修改
  `apps/web/index.html` 的内联脚本时必须同步更新两个 Caddyfile 的哈希；
  `apps/web/src/__tests__/csp-hash.test.ts` 会在漂移时报错）。
  `style-src` 保留 `unsafe-inline`（净化后的文章 style 属性需要）；
  `img-src`/`media-src` 允许远端（文章内嵌第三方媒体）。
- 另有 HSTS（max-age=1y）、`Permissions-Policy`（camera/mic/geo 关闭）、
  `frame-ancestors 'none'`。

### 3.3 请求体上限与限流（0021）

- 全局请求体 4 MiB 上限（超限 → 稳定 413 `request_too_large`）；
  OPML 导入保留自身更严格的 2 MiB 边界。
- 昂贵控制面路由有进程内固定窗口限流（超限 → 稳定 429
  `rate_limited` + `Retry-After`）：restore 10/min、backups 12/min、
  feed 预览/来源发现 30/min、AI/MT 生成 120/min、RSSHub 变更 60/min。
  阅读类 GET 不限流。阈值面向单用户，进程重启即重置。

### 3.4 多设备设置冲突（0021）

`GET/PATCH /api/v1/settings` 暴露内容哈希 `revision`；PATCH 可带
`baseRevision`，与当前不一致时返回稳定 409 `app_settings_conflict`
（另一设备已写入）。Web 同步层会自动 re-hydrate 并重试一次；不带
`baseRevision` 的调用保持 last-write-wins（旧客户端兼容）。

## 4. Health / readiness

- `GET /health/live` — 进程存活（**仅容器内**：Caddy 只反代 `/api/*`）。
- `GET /health/ready` — 核心（lumi.sqlite）不可用才 503；FreshRSS/RSSHub
  故障不影响 readiness（AD-0018-3 失败隔离）。同样**仅容器内**可达。
- `GET /api/v1/operations/status` — 各依赖真实探测（延迟/类型化错误），
  经 Caddy `/api/*` 反代对外可达；UI 在「设置 → 账户与服务」展示。

## 5. Logs

- `json-file` 轮转（10 MB × 3）已配置；查看：`docker compose logs bff`。
- 日志不含秘密（0018 生产 smoke 验证）；错误消息为脱敏安全文本。

## 6. Backups / WebDAV / Restore

- UI 入口：设置 →「数据控制」（配置迁移 / 完整备份 / 备份历史 /
  WebDAV / 恢复同页）。API 见 `docs/milestones/0018-*.md`。
- 备份内容：lumi.sqlite（在线备份 API）+ FreshRSS 数据目录（只读卷 +
  SQLite online backup，含 config.php 与用户 db.sqlite）。
- **备份必须当作敏感文件保管**：Lumi 自身的秘密值（AI/WebDAV/RSSHub/
  FreshRSS API 密码、auth 哈希——见 manifest.secretPolicy.excludedSecrets）
  **不进备份**，恢复后需重新配置；但 **FreshRSS 数据目录本身可能含凭据
  敏感材料**（如 FreshRSS 用户口令哈希、其自身配置），因此归档不是
  “无敏感内容”。
- 存储保护：本机 `data/backups/` 应限制文件系统权限；WebDAV 传输走
  TLS（http 仅允许私网/回环），远端目录需相应的访问控制。切勿把
  备份归档提交到 Git 或上传到不受信的位置。
- 单并发 job；阶段真实上报；恢复前自动创建当前状态安全备份；
  恢复需显式输入 `RESTORE`。
- FreshRSS 数据恢复为**离线恢复**：文件就绪于
  `data/restore-staging/restore-ready/freshrss/`，operator 按官方 compose
  步骤自行覆盖 FreshRSS 卷（Lumi 不写运行中的 FreshRSS）。
- WebDAV：服务器端上传；密码写只读；http 仅允许私网/回环地址。

### 6.1 完整备份能力预检与 FreshRSS 数据目录

`GET /api/v1/backups/capabilities` 在点击前如实回答"完整备份现在能包含
什么"：FreshRSS 数据目录是否配置/存在/可读、数据库类型（外部
MySQL/PostgreSQL 不在数据目录里 → 明确拒绝并提示直接备份数据库）、
将包含的组件清单。UI（设置 → 数据控制 → 备份概览）展示同一结论；
后端执行时用同一预检逻辑再校验，预检失败原因与执行失败原因一致。

**FreshRSS 权限边界（重要）**：FreshRSS 把 `data/users/<user>/`
建为 `0770 root:www-data`。因此：

- **生产 Compose（支持拓扑）**：`docker-compose.prod.yml` 已给 BFF 容器
  加 `group_add: ["33"]`（www-data 组），BFF（uid 10001）可只读遍历。
  旧部署升级后需 `up -d --force-recreate bff` 重建容器生效。
- **开发栈（宿主机 BFF + 容器 FreshRSS）**：宿主机进程默认读不到命名卷，
  也进不了 0770 用户目录。完整备份需一次性迁移到 bind mount：
  见 `docker-compose.dev-backup.yml` 头注释（数据保留，可回滚），并对
  数据目录执行一次 `chmod -R a+rX`（在容器内执行：
  `docker exec freshrss sh -c 'chmod -R a+rX /var/www/FreshRSS/data'`；
  之后新写入的缓存等文件若再次变严，预检会如实报 `unreadable_entries`，
  重跑同一条命令即可）。BFF 侧在 `services/bff/.env` 设
  `FRESHRSS_DATA_DIR` 指向同一目录。
- 预检/执行对"目录存在但部分不可读"一律诚实失败
  （`unreadable_entries`），绝不产出缺用户数据库的"假完整包"。

## 7. Upgrade / Rollback

```bash
# 升级前
docker compose -f docker-compose.prod.yml exec bff true   # 确认健康
# 在 UI 创建完整备份（或 API POST /api/v1/backups）
git pull && git checkout <release-tag>
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec bff \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).status)"
```

- 回滚 = `git checkout <上一 tag>` 重建镜像 + **恢复升级前安全备份**
  （SQLite schema 不做二进制降级；数据库不兼容时唯一受支持路径是恢复
  升级前备份）。此流程在 0019 C11 完成真实演练。

## 8. Disaster recovery

1. 部署全新栈（§1）。
2. 取回最近备份（本机卷或 WebDAV）。
3. 「数据控制 → 备份历史 → 从此备份恢复」→ 预览校验 → 输入 `RESTORE` 执行。
4. FreshRSS 数据按 §6 离线恢复；`/health/ready` + 阅读流程验证。
5. 损坏 checksum / 不兼容版本会被拒绝（有回归测试覆盖）。

## 9. Troubleshooting

| 症状 | 处置 |
|---|---|
| 界面新功能调用接口返回 404（如备份/RSSHub 配置） | 线上 BFF 是旧镜像：`docker compose -f docker-compose.prod.yml up -d --build`（必须带 `--build`）。核对「关于」页前端构建与服务端 (BFF) commit 是否一致（`GET /api/v1/version`） |
| 容器反复重启、auth 不生效 | `.env.prod` auth 只设了一个变量（entrypoint FATAL）或 bcrypt `$` 未转义 `$$` |
| FreshRSS unhealthy → BFF 不启动 | healthcheck = 官方 `php cli/health.php`；确认 FreshRSS 初始化完成（首次安装） |
| RSSHub 不可用 | 只影响来源发现/预览；阅读不受影响；`docker compose restart rsshub` |
| 恢复后残留 interrupted 记录 | 正常：恢复会把快照中的陈旧运行态标记为 interrupted（审计） |
| 磁盘增长 | `data/backups/` 与 `data/restore-staging/` 定期清理（staging 会话与 24h 前下载自动清理） |

## 10. Data ownership

- 订阅/文章状态：FreshRSS（SQLite，`freshrss-data` 卷）——唯一真源。
- 设置/AI 缓存/对话/备份账本：`lumi-data` 卷内 `lumi.sqlite`。
- RSSHub 凭据 / WebDAV 密码：`data/secrets.json`（0600）。
- 全部数据在用户自托管基础设施内，Lumi 不外发。
