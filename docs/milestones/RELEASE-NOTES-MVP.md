# Release Notes — LumiRSS MVP (0018 + 0019)

> 状态：release-ready 分支 `feat/0019-mvp-stabilization-release`。
> 正式 tag 在分支合并 main 后创建。

## 0018 — Production, Operations & Backup

**生产部署**
- `docker-compose.prod.yml`：Caddy 统一入口（静态 Web + /api 反代），
  FreshRSS/RSSHub 仅内部网络；持久卷、healthcheck、重启策略、日志轮转、
  资源限额；无 Docker socket；FreshRSS 数据只读挂载用于一致性备份。
- 单用户访问控制：Caddy Basic Auth（bcrypt），可关闭（受信内网）；
  TLS 自动化（域名 → Let's Encrypt，localhost → 本地 CA）。
- `.env.prod.example`：完整配置模板，含 `$$` 转义等关键注意事项。

**运维**
- `/health/ready` + `/api/v1/operations/status`：真实依赖探测
  （FreshRSS / RSSHub / SQLite），无假指标；RSSHub 故障不影响阅读。

**RSSHub 控制中心**
- 33 键 typed allow-list（键名/类型/分组/默认值），desired/applied 双态、
  restartRequired 如实标记；secret 写只读（永不回显）；导出 `.env` 片段
  （secret 只渲染键名）；无任意 env / shell / 自动重启。

**备份 / WebDAV / 恢复**
- 版本化 manifest（backupSchemaVersion=1）+ 每文件 SHA-256；
  lumi.sqlite 在线备份 + FreshRSS 数据一致性备份；WebDAV 服务器端上传
  （TLS 校验、同源 redirect、有界响应）。
- 分阶段恢复：预览（checksum + 兼容性）→ 当前状态安全备份 → 显式
  `RESTORE` 确认 → 执行 → 健康验证；失败保留安全备份与原备份；
  恢复执行在 backup_jobs 留审计记录。
- UI：备份概览 / 历史 / WebDAV / 分阶段恢复向导 / 配置迁移（0017 能力
  保留），响应式 + 键盘 + 明暗主题。

## 0019 — MVP Stabilization & Release

- Playwright E2E 体系：桌面/移动完整 journeys（订阅、Reader、AI mock、
  OPML 上传、备份恢复向导、搜索诚实边界）× 多视口 × 明暗主题。
- 可访问性：axe 扫描（0 critical / 0 serious 硬门）；修复 row 语义、
  文本对比度（明暗主题 secondary/tertiary/accent-text token）、
  激活态导航可读性。
- 性能预算冻结（0018 基线：LCP ≤ 200ms 本地、CLS ≈ 0、主 chunk
  1.10 MB / gzip 475 KB，无回归）。
- CI（`.github/workflows/ci.yml`）：BFF 测试 / Web 测试+lint+build /
  Playwright 冒烟 / compose 校验；无真实凭据。
- Operator 文档（`docs/development/operations.md`）与升级/回滚、灾难
  恢复演练记录。

## Known limitations

- BFF 全局结构化日志 / 关联 ID 未实现（operations/status 内含延迟与
  错误分类）；规划于后续里程碑。
- `rsshub_secret_not_found` 错误类型保留但不可触发（删除 secret 为幂等
  204）。
- BFF 镜像构建依赖未 pin（`pip install .`）；web（Caddy）服务无
  healthcheck。
- 全局搜索未实现（入口诚实说明）。
