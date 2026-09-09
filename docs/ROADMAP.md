# LumiRSS Roadmap

> What comes next, in order. Completed milestones and release notes:
> [history/milestones.md](history/milestones.md)

## Now

- MVP 稳定化：以真实使用反馈驱动缺陷修复与体验打磨，不开新的大功能面。

## Next（候选，立项由用户批准的 spec 决定）

- BFF 结构化日志与关联 ID（发布时已知限制，operations/status 已含延迟
  与错误分类）；
- BFF 生产镜像依赖 pin；web（Caddy）服务 healthcheck（发布时已知限制）；
- 稍后读（read-later）跨设备同步——落地时应迁到 Lumi SQLite 而非第三方
  存储（见 [explanation/reuse-policy.md](explanation/reuse-policy.md)）。

## Later

- **Phase 2 — Knowledge Workbench**：web clipping、结构化 JSON/API 来源、
  邮件 newsletter、Obsidian library connector、统一来源注册表、
  agent workspace。

## Explicitly deferred / rejected

- 多用户 / 多租户、公共互联网硬化（单用户是产品前提）；
- PWA 离线缓存 / Service Worker / Push（manifest 已有，其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、原生移动 App；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [explanation/search.md](explanation/search.md)）。
