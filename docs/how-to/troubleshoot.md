# Troubleshooting（故障排查）

> 排查入口：`./lumirss doctor`（docker/compose/.env.prod/DNS/容器健康/
> 磁盘/备份目录 PASS/WARN/FAIL）与 `./lumirss status`（容器、健康、
> web/bff commit 与镜像 tag）。日志：`./lumirss logs [service]`。

## 常见症状

| 症状 | 处置 |
|---|---|
| **RSS 永不自动更新**（只有手动刷新才出现新文章） | 逐层查：① 上游 feed 是否真有新条目（用阅读器直开 feed URL）；② FreshRSS 容器是否设置了 `CRON_MIN`——缺省时容器内置 cron 不启动，订阅永不自动刷新（2026-09-18 前的 compose 正是此问题）。修复：compose 的 freshrss 加 `CRON_MIN: "13,43"` 并 `docker compose up -d freshrss`；验证 `docker exec <freshrss容器> cat /var/spool/cron/crontabs/*` 有 actualize 行，且 freshrss 日志在对应分钟出现抓取记录；③ 投影滞后：`GET /api/v1/sources/volume` 看 lastSyncedAt 是否推进 |
| 界面新功能调用接口返回 404（如备份/RSSHub 配置） | 线上 BFF 是旧镜像：检查部署机是否拉到新 tag（`./lumirss status` 看 image tag / `GET /api/v1/version` 的 commit）→ `LUMIRSS_IMAGE_TAG=<新tag> ./lumirss update`（或手工 `docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d`）。生产是 prebuilt-only：`--build` 会被拒绝，本地构建不是受支持的修复路径 |
| 容器反复重启、auth 不生效 | `.env.prod` auth 只设了一个变量（entrypoint FATAL）或 bcrypt `$` 未转义 `$$`（规则见 [../reference/configuration.md](../reference/configuration.md)） |
| FreshRSS unhealthy → BFF 不启动 | healthcheck = 官方 `php cli/health.php`；确认 FreshRSS 初始化完成（首次安装需先完成安装向导） |
| RSSHub 不可用 | 只影响来源发现/预览；阅读不受影响；`docker compose restart rsshub` |
| 设置 `LUMIRSS_INTERNAL_TOKEN` 后 API 全 401 | 直连 BFF 的调用必须带 `X-Lumi-Token` 头；经 Caddy 的浏览器访问不受影响。两个容器读同一份 `.env.prod`，只设一侧会导致全 401 或无效果 |
| 完整备份报 `unreadable_entries` | FreshRSS 用户目录权限（0770 root:www-data）；处置见 [backup-restore.md](backup-restore.md)「权限边界」 |
| 恢复后残留 interrupted 记录 | 正常：恢复会把快照中的陈旧运行态标记为 interrupted（审计） |
| 磁盘增长 | 清理 `data/backups/` 与 `data/restore-staging/`（见 [backup-restore.md](backup-restore.md)） |
| 部署时 DNS/端口告警 | `./lumirss deploy` preflight 会告警域名未解析、80/443 被占用、磁盘不足；先解决再部署 |
| 机器推送（收件箱 ingest / 邮件 webhook）在 session 模式下 401 | 这两条是机器到机器端点（bearer 鉴权），外层 host Caddy 若开了 basic auth 会先拦截它们：在 host 反代上对 `/api/v1/inbox/ingest/*` 与 `/api/mail/ingest/*` 放行（仍受 BFF 侧 bearer 保护） |
| 成员账号 RSS 绑定显示「待就绪」 | 激活时 FreshRSS 账号池为空（诚实状态，账号其余功能不受影响）：运营者用 `scripts/freshrss_pool.sh` 补池后即可绑定；池状态见 `/admin`（详见 [invite-members.md](invite-members.md)） |
| 成员登录返回 401 且确认密码正确 | 账号可能被暂停（`/admin` → 成员 → 恢复）或邀请/恢复链接已过期（一次性限时，过期后请运营者重发）；owner 密码遗忘用 `./lumirss set-password` |
| 回滚到旧镜像后邮件桥报错 | 回滚快照的 schema 是按当时版本建的：回退跨越 0018（`mail_seen` 重建）之前的镜像时，须先把 DB 回滚到对应 schema 版本的快照，不能只换镜像 tag。**2.0.0 起数据布局改变（控制库 + 每用户库），跨该版本回退只能恢复升级前备份** |

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

## 应用内维护与隐私工具（设置中心；普通排障从这里开始）

- **脱敏诊断包**：设置 → 运维 → 导出诊断包。仅含版本/schema/依赖状态/
  错误计数/配置「有无」布尔——绝不含凭据值或文章正文，导出前可预览。
- **操作记录**：设置 → 运维。合并展示后台任务/AI 生成/导入/日报期号
  的有界脱敏时间线（成功与失败都如实）。
- **会话管理**：设置 → 账户与安全。列出有效会话（含"本机"标记），
  可撤销指定会话或全部（改密亦会撤销全部旧会话）。
- **派生数据保留策略**：设置 → 存储。为过期 AI 结果版本等可清理派生
  数据设保留天数；默认关闭，先预览（区分记录数与字节）再启用；原文、
  批注、笔记、卡片、凭据与运行中任务不受清理影响。
- **Library 回收站**：书签/剪藏删除先进回收站（可恢复、可搜索期外
  才不可见），永久删除需显式确认；FreshRSS 条目与 Vault 文件永不进入
  该流程。
- **设置历史与撤销**：设置 → 数据控制。最近设置变更可单笔撤销（按
  字段冲突检查，已被后续修改的键如实跳过）。
- **多设备设置冲突**：两台设备同时修改时不再静默覆盖——出现逐字段
  对照对话框（本地候选 vs 服务端当前），由你选择后重新提交。
- **本机草稿恢复**：笔记/批注编辑器的未保存草稿留在本机（不上传）；
  意外关闭后重新打开会提示恢复/放弃/对照，登出即清空。
- **演示隐私遮罩**：全局菜单可临时把标题/来源等敏感文本替换为遮罩块
  （真实替换 DOM 文本，非视觉模糊）；刷新自动退出。
- **登录失败限流分桶**：反代后按可信代理的 `X-Forwarded-For` 最后一跳
  分桶（见 `LUMIRSS_TRUSTED_PROXY_NETWORKS`，[configuration.md]
  (../reference/configuration.md)）；单个客户端刷失败不再锁死其他网络。
