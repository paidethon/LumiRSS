# Deploy & Operate（生产部署与运维）

> 面向自托管 operator。对应实现：`docker-compose.prod.yml`、`./lumirss`
> 生命周期脚本、`services/bff`、`apps/web/Dockerfile`（Caddy +
> docker-entrypoint.sh）。配置键语义统一见
> [../reference/configuration.md](../reference/configuration.md)。

## 1. 一键部署（./lumirss）

全新 Ubuntu 22.04/24.04 x86_64 服务器（需 docker engine + compose 插件、
git、curl）：

```bash
git clone https://github.com/paidethon/LumiRSS.git && cd LumiRSS
sudo ./lumirss deploy
```

`deploy` 会：preflight（docker/compose/curl、DNS、80/443 占用、磁盘）→
生成并引导填写 `.env.prod`（自动生成 `LUMIRSS_INTERNAL_TOKEN`；交互式
询问域名与登录账号，密码经 `caddy hash-password` 生成 `$$` 转义后的
bcrypt 哈希）→ 拉取 GHCR 预构建镜像（失败自动本地构建）→ `up -d` →
等待 `/health/ready` → 打印 status。

非交互部署（如脚本/云-init）：`LUMIRSS_DOMAIN`、`LUMIRSS_AUTH_USER`、
`LUMIRSS_AUTH_HASH`、`LUMIRSS_AUTH_PASSWORD` 环境变量覆盖询问；
`./lumirss deploy --dry-run` 只做配置校验；`--build` 强制本地构建。

## 2. 生命周期子命令

| 命令 | 作用 |
|---|---|
| `./lumirss update [--build]` | 备份 → 拉取/构建镜像 → `up -d` → 健康检查 |
| `./lumirss status` | 容器状态、健康、web/bff 版本（commit）与镜像 tag |
| `./lumirss logs [service] [-f]` | 全栈或单服务日志 |
| `./lumirss backup` | lumi-data + freshrss-data 卷 tar.gz + 配置归档到 `./backups/`（`LUMIRSS_BACKUP_DIR` 可改） |
| `./lumirss restore <backup.tar.gz> [--yes]` | 停 bff → 覆盖恢复卷 → 启动 → 健康检查（破坏性，需输入 `RESTORE` 或 `--yes`） |
| `./lumirss doctor` | PASS/WARN/FAIL 诊断（docker、compose、.env.prod、DNS、容器与健康、磁盘、备份目录） |
| `./lumirss rollback` | 回到上一镜像 tag + 恢复上一份 `.env.prod` 快照 |

镜像默认取 GHCR：`ghcr.io/paidethon/lumirss-web` /
`ghcr.io/paidethon/lumirss-bff`，tag 由 `LUMIRSS_IMAGE_TAG` 控制
（默认 `latest`）；compose 的 `build:` 段是本地构建回退
（`./lumirss deploy --build` 或拉取失败时自动使用，构建时注入
`LUMIRSS_BUILD_COMMIT` 作版本溯源）。

> 在同一台机器上测试而不影响正式栈：设置独立的
> `LUMIRSS_HTTP_PORT` / `LUMIRSS_HTTPS_PORT` / `COMPOSE_PROJECT_NAME`
> 再部署（见 [../reference/configuration.md](../reference/configuration.md)）。

## 3. 手工部署（等价路径）

```bash
cp .env.prod.example .env.prod   # 填写真实值；$ 必须写成 $$（见配置参考）
docker compose -f docker-compose.prod.yml up -d --build
```

- 唯一公网入口是 `web`（Caddy，80/443）；FreshRSS / RSSHub 只在内部网络。
- BFF **不发布任何宿主端口**：`/health/live`、`/health/ready` 只能容器内
  访问；外部监控走经反代的 `/api/v1/operations/status`。
- FreshRSS / RSSHub 镜像按 digest/版本 pin（不随系统升级漂移）。
- 最低资源：2 vCPU / 2 GB RAM / 10 GB 磁盘（RSSHub 峰值内存最高）。

就绪检查（与镜像 HEALTHCHECK 同一手法，从容器内执行）：

```bash
docker compose -f docker-compose.prod.yml exec bff \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).status)"
```

公网入口自检：`curl -fsS -o /dev/null http://127.0.0.1/`（`DOMAIN` 强制
HTTPS 时用 `https://<DOMAIN>/`；自签本地证书需 `-k`）。

## 4. 访问控制与边缘安全

- **Caddy auth / noauth**：`LUMIRSS_AUTH_USER` + `LUMIRSS_AUTH_HASH`
  都设置 → 渲染 `Caddyfile.auth`（basic_auth，bcrypt）；都为空 →
  `Caddyfile.noauth`（受信内网/已有外层认证）。**只设一个容器拒绝启动**
  （防止半配置静默关闭访问控制）。Tailscale / Cloudflare Access 等外层
  方案可替换内置 basic auth，但不要无意叠加多套认证。
- **TLS 三态**：真实域名 → Let's Encrypt；`localhost` → 自签 + 强制
  HTTPS；`http://:80` 形式 → 纯 HTTP（仅内网调试）。
- **BFF internal token（可选但推荐）**：`.env.prod` 设置
  `LUMIRSS_INTERNAL_TOKEN` 后，BFF 拒绝一切不带匹配 `X-Lumi-Token` 头的
  `/api/*` 请求（401；`/health/*` 豁免）。Caddy entrypoint 自动注入该头，
  浏览器使用不受影响；只有绕过 Caddy 直连 BFF 的内网调用被拒。两个容器
  读同一份 `.env.prod`，要么都设要么都不设。
- **安全响应头**：nosniff / X-Frame-Options DENY / no-referrer / HSTS /
  Permissions-Policy / CSP。CSP 的 `script-src 'self'` + 内联主题脚本按
  sha256 pin（修改 `apps/web/index.html` 内联脚本时必须同步更新两个
  Caddyfile 的哈希，漂移会被 `apps/web/src/__tests__/csp-hash.test.ts`
  捕获）；`style-src` 保留 `unsafe-inline`（净化后的文章 style 属性需要）；
  `img-src`/`media-src` 允许远端；`frame-ancestors 'none'`。
- **BFF 侧硬化**：全局请求体 4 MiB 上限（超限 → 稳定 413
  `request_too_large`；OPML 导入保留更严格的 2 MiB）；昂贵控制面路由
  进程内固定窗口限流（超限 → 429 `rate_limited` + `Retry-After`：
  restore 10/min、backups 12/min、feed 预览/来源发现 30/min、AI/MT
  生成 120/min、RSSHub 变更 60/min；阅读类 GET 不限流；阈值面向单用户，
  进程重启即重置）。
- **多设备设置冲突**：`PATCH /api/v1/settings` 可带 `baseRevision`，与
  当前不一致返回 409 `app_settings_conflict`；Web 同步层自动 re-hydrate
  并重试一次；不带 `baseRevision` 保持 last-write-wins（旧客户端兼容）。

## 5. Health / readiness / 日志

- `GET /health/live` — 进程存活（仅容器内）。
- `GET /health/ready` — 核心依赖（lumi.sqlite）不可用才 503；
  FreshRSS/RSSHub 故障不影响 readiness（失败隔离）。
- `GET /api/v1/operations/status` — 各依赖真实探测（延迟/类型化错误），
  经 Caddy 对外可达；UI 在「设置 → 账户与服务」展示。
- 日志：`json-file` 轮转（10 MB × 3）；`./lumirss logs bff` 查看；
  日志不含秘密，错误消息为脱敏安全文本。

## 6. 升级与回滚

```bash
./lumirss update        # 备份 → 拉取 → up → 健康检查（推荐）
```

手工等价：确认容器健康 → 在 UI 创建完整备份 →
`git pull && git checkout <release-tag>` →
`docker compose -f docker-compose.prod.yml up -d --build` → 就绪检查。

回滚：`./lumirss rollback`（上一镜像 tag + 上一份配置快照）。SQLite
schema 不做二进制降级；数据库不兼容时唯一受支持路径是恢复升级前备份
（见 [backup-restore.md](backup-restore.md)）。
