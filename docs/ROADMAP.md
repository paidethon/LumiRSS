# LumiRSS Roadmap

> What comes next, in order. Completed milestones and release notes:
> [history/milestones.md](history/milestones.md)。功能状态以本文与
> [explanation/architecture.md](explanation/architecture.md) 为准。

## Current state（2026-09）

MVP（0000–0020）、Phase 2 knowledge workbench、Phase 2 recovery 返工、
2.0.0 邀请制多账户（[ADR 0005](decisions/0005-invite-multi-account.md)，
运营者操作见 [how-to/invite-members.md](how-to/invite-members.md)）与
默认关闭的可选公开注册（[ADR 0006](decisions/0006-public-registration.md)）
均已合入 main 并部署生产。

3.0.0 重建批次在此之上小步补齐（用户视角明细见仓库根 `CHANGELOG.md`）：
来源中心九类汇总（`GET /api/v1/sources/summary`）、Obsidian 服务端受限
导出（[ADR 0007](decisions/0007-obsidian-server-side-export.md)）、AI 日报
（原 GPT 日报）、邮件简报内容页（逐次发送账本 + 重试只补未送达）、RAG
索引内容页、OPML 导入 RSSHub 自动匹配、内置 8 款开源阅读字体（R08）、
49 项用户偏好上云（R25）、单容器拓扑
（[ADR 0008](decisions/0008-single-container-topology.md)，`./lumirss
deploy --single` / `migrate-single` / `rollback-single`）；认证以应用
会话为主，basic auth 转为兼容可选项（生产实例切换执行中）。机读功能
清单见 [feature-manifest.json](feature-manifest.json)；FreshRSS/RSSHub
上游全功能对照见
[public/reference/upstream-feature-matrix.html](public/reference/upstream-feature-matrix.html)。

本文不再维护分批功能清单——版本化的用户视角
变化见仓库根 `CHANGELOG.md`（2.0.1 各批次按其发布节奏逐条补入），逐项
任务状态以机读台账
[implementation-status.json](implementation-status.json) 为准（`pnpm
check:dashboard` 漂移守卫，看板接法见
[how-to/deploy.md](how-to/deploy.md) §8），批次历史归档见
[history/milestones.md](history/milestones.md)，冻结的 recovery 审计
账本见 [audits/phase2-recovery.md](audits/phase2-recovery.md)。已按
批次合入但未进入任何版本说明的更早增量（2.0.0 前合入的来源管理增强
N012/N013/N015、NE1 阅读排版批次等）以 `git log` 为准。

## Next（候选，立项由用户批准的 spec 决定）

- Agent 消息 / RAG 端点的 Web 侧本地 interface 迁移到生成 schema 别名
  （response_model 已补齐，剩余为 Web 消费端重构）；
- 剪藏/快照阅读体验打磨；
- 来源运维 UI 的 J4 类合并契约回归排查（ny1/nx1 批次）。

> 更新（FIX-182/ARCH-03，2026-10）：J4 AI journey 已按现行 AI 设置页
> 契约（用途分配 / Profile / 默认配置的精确锚定选择器）重写并恢复为 CI
> 必需旅程——原「CI 门扩展：J4 因 purpose-profiles 契约漂移暂不在门内」
> 条目不再成立，已移除。

## Explicitly deferred / rejected

- WebDAV vault、Bergamot 本地翻译（无中文模型）、外部向量库服务
  （sqlite-vec 单文件已够）；
- 多租户形态、公共互联网硬化（邀请制小规模多账户与默认关闭的可选公开
  注册已实现，见 [ADR 0006](decisions/0006-public-registration.md)；
  对公网开放前的加固仍不在范围内）；
- PWA Push / 后台同步（app-shell 离线缓存已实现；其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、原生移动 App；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [explanation/search.md](explanation/search.md)）。
