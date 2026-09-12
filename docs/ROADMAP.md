# LumiRSS Roadmap

> What comes next, in order. Completed milestones and release notes:
> [history/milestones.md](history/milestones.md)

## Now

- **Phase 2 recovery（2026-09）**：对已合并的 Phase 2 做纠偏与返工——
  统一 ItemRef 解析、read-later 服务端化、剪藏/快照服务端可信管线、
  API 来源 Atom/ETag/last-known-good、邮件桥全链路（webhook/IMAP/摘要）、
  Obsidian 只读挂载契约、RAG 真向量索引、Agent 真实 provider 契约与
  审批加固、翻译 user activation、导航/文档与真实能力对齐。进度与证据：
  [audits/phase2-recovery.md](audits/phase2-recovery.md)。

## Next（候选，立项由用户批准的 spec 决定）

- BFF 结构化日志与关联 ID（发布时已知限制，operations/status 已含延迟
  与错误分类）；
- BFF 生产镜像依赖 pin；web（Caddy）服务 healthcheck（发布时已知限制）；
- 摘要时区设置（当前为服务器本地时区，见邮件桥文档）；
- 剪藏/快照阅读体验打磨（依赖 Gate 2 服务端管线落地后的反馈）。

## Phase 2 — Knowledge Workbench（已合入 main，2026-09 recovery 返工中）

- 主体功能面：Library 域（书签/工作区/剪藏/快照资产）、本地翻译加固、
  API 来源（JMESPath→Atom→FreshRSS）、邮件桥+摘要、
  Obsidian 只读投影、统一搜索双腿+联邦收藏、低内存 RAG
  （sqlite-vec + fastembed，显式启用+空闲卸载）、Agent 工作台
  （服务端强制审批）、统一标签+派生图谱。
  已交付 ≠ 可用：recovery 之前多个主链路是外壳（见
  [audits/phase2-recovery.md](audits/phase2-recovery.md) 的 P0 账本），
  可用性以该账本的验证状态为准。
- 明确不做：WebDAV vault、Bergamot 本地翻译（无中文模型）、
  多用户形态、向量库服务（sqlite-vec 单文件已够）。

## Explicitly deferred / rejected

- 多用户 / 多租户、公共互联网硬化（单用户是产品前提）；
- PWA 离线缓存 / Service Worker / Push（manifest 已有，其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、原生移动 App；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [explanation/search.md](explanation/search.md)）。
