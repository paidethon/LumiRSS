# Troubleshooting（故障排查）

> 排查入口：`./lumirss doctor`（docker/compose/.env.prod/DNS/容器健康/
> 磁盘/备份目录 PASS/WARN/FAIL）与 `./lumirss status`（容器、健康、
> web/bff commit 与镜像 tag）。日志：`./lumirss logs [service]`。

## 常见症状

| 症状 | 处置 |
|---|---|
| 界面新功能调用接口返回 404（如备份/RSSHub 配置） | 线上 BFF 是旧镜像：`./lumirss update --build`（或手工 `docker compose -f docker-compose.prod.yml up -d --build`，必须带 `--build`）。核对「关于」页前端构建与服务端 (BFF) commit 是否一致（`GET /api/v1/version`） |
| 容器反复重启、auth 不生效 | `.env.prod` auth 只设了一个变量（entrypoint FATAL）或 bcrypt `$` 未转义 `$$`（规则见 [../reference/configuration.md](../reference/configuration.md)） |
| FreshRSS unhealthy → BFF 不启动 | healthcheck = 官方 `php cli/health.php`；确认 FreshRSS 初始化完成（首次安装需先完成安装向导） |
| RSSHub 不可用 | 只影响来源发现/预览；阅读不受影响；`docker compose restart rsshub` |
| 设置 `LUMIRSS_INTERNAL_TOKEN` 后 API 全 401 | 直连 BFF 的调用必须带 `X-Lumi-Token` 头；经 Caddy 的浏览器访问不受影响。两个容器读同一份 `.env.prod`，只设一侧会导致全 401 或无效果 |
| 完整备份报 `unreadable_entries` | FreshRSS 用户目录权限（0770 root:www-data）；处置见 [backup-restore.md](backup-restore.md)「权限边界」 |
| 恢复后残留 interrupted 记录 | 正常：恢复会把快照中的陈旧运行态标记为 interrupted（审计） |
| 磁盘增长 | 清理 `data/backups/` 与 `data/restore-staging/`（见 [backup-restore.md](backup-restore.md)） |
| 部署时 DNS/端口告警 | `./lumirss deploy` preflight 会告警域名未解析、80/443 被占用、磁盘不足；先解决再部署 |

## 首次安装清单

1. `./lumirss deploy`（或手工路径，见 [deploy.md](deploy.md)）；
2. `DOMAIN` 填真实域名时确认 DNS 已解析（Let's Encrypt 才能签发）；
3. 浏览器登录账号：`LUMIRSS_AUTH_USER` + `LUMIRSS_AUTH_HASH` 要么都设、
   要么都不设；
4. FreshRSS 初始化完成后 BFF 才会启动（healthcheck 门控）；
5. 进入 Lumi「设置 → 账户与服务」确认各依赖真实状态（不是假指标）。

## 诊断端点

- `GET /health/live` / `GET /health/ready` — 仅容器内可达（Caddy 只反代
  `/api/*`）；`/health/ready` 只由 lumi.sqlite 决定。
- `GET /api/v1/operations/status` — 各依赖真实探测（延迟/类型化错误），
  经反代对外可达。
