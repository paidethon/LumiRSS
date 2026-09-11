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

## Phase 2 — Knowledge Workbench（integration 分支进行中，2026-09）

- 已落地（见 [research/phase2/](research/phase2/README.md) 实施规格）：
  Library 域（书签/工作区/剪藏/快照资产）、本地翻译加固、
  API 来源（JMESPath→Atom→FreshRSS）、邮件桥+摘要、
  Obsidian 只读投影、统一搜索双腿+联邦收藏、低内存 RAG
  （sqlite-vec + fastembed，显式启用+空闲卸载）、Agent 工作台
  （服务端强制审批）、统一标签+派生图谱。
- 明确不做：WebDAV vault、Bergamot 本地翻译（无中文模型）、
  多用户形态、向量库服务（sqlite-vec 单文件已够）。

## Explicitly deferred / rejected

- 多用户 / 多租户、公共互联网硬化（单用户是产品前提）；
- PWA 离线缓存 / Service Worker / Push（manifest 已有，其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、原生移动 App；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [explanation/search.md](explanation/search.md)）。
