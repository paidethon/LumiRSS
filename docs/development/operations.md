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
  env `AI_API_KEY` 保留为默认配置的回退。

## 3. Caddy auth / noauth

- 两者都设置 → 渲染 `Caddyfile.auth`（basic_auth，bcrypt）。
- 都为空 → `Caddyfile.noauth`（受信内网/已有外层认证）。
- 安全响应头（nosniff / DENY / no-referrer）两种模式都启用。

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
