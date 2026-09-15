# LumiRSS Roadmap

> What comes next, in order. Completed milestones and release notes:
> [history/milestones.md](history/milestones.md)。功能状态以本文与
> [explanation/architecture.md](explanation/architecture.md) 为准。

## Current state（2026-09）

- **MVP（0000–0020）与 Phase 2 knowledge workbench 均已合入 main**：
  Library 域（书签/剪藏/快照）、工作区与服务端稍后读、收件箱推送来源 +
  统一来源注册表（0021）、API 来源（JMESPath→Atom→FreshRSS）、邮件桥 +
  摘要、Obsidian 只读投影、统一搜索双腿 + 联邦收藏、标签/图谱、低内存
  RAG、Agent 工作台（服务端强制审批）。
- **Phase 2 recovery（2026-09-13/14）已完成并部署生产**：13 个 P0 返工
  全部 `production_verified`，Gate 8 smoke 15/15。完整账本（已冻结）：
  [audits/phase2-recovery.md](audits/phase2-recovery.md)。
- 明确不做：WebDAV vault、Bergamot 本地翻译（无中文模型）、多用户形态、
  外部向量库服务（sqlite-vec 单文件已够）。

## Next（候选，立项由用户批准的 spec 决定）

- 安全加固（2026-09-15 审计遗留 P2）：邮件桥/收件箱 bearer secret 入库
  SQLite 并随备份归档外流（应迁 SecretsStore 或文档化轮换策略）；登录
  失败限流在 Caddy 后退化为单桶（所有客户端共享 5 次/分钟，可被第三方
  锁定登录——需 X-Forwarded-For 分桶或文档化+上调阈值）；
- BFF 结构化日志与关联 ID（发布时已知限制，operations/status 已含延迟
  与错误分类）；
- BFF 生产镜像依赖 pin；web（Caddy）服务 healthcheck（发布时已知限制）；
- Agent 消息 / RAG 状态端点补 `response_model`（OpenAPI 未收录，
  Web 侧暂以本地 interface 对照维护）；
- IMAP 收信通路的前端配置 UI（后端 4 端点已存在，Q-P1-07）；
- 摘要时区设置（当前为服务器本地时区，见邮件桥文档）；
- 剪藏/快照阅读体验打磨；
- CI 增加 Playwright 全量 journey 门（boot e2e compose 栈；当前 CI 只跑
  静态冒烟 1/32）。

## Explicitly deferred / rejected

- 多用户 / 多租户、公共互联网硬化（单用户是产品前提）；
- PWA Push / 后台同步（app-shell 离线缓存已实现；其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、原生移动 App；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [explanation/search.md](explanation/search.md)）。
