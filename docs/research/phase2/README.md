# Phase 2 基础研究文档(index)

> 本目录是 **研究文档**,不属于任何 agent 的默认预加载内容(见 AGENTS.md
> §10:普通任务不读取本目录;仅相关 milestone 打开对应报告)。

## 报告清单

| 文件 | 主题 | 状态 |
|---|---|---|
| [00-platform-architecture](00-platform-architecture.md) | Library Domain / ItemRef / Source Registry / 安全与预算基线 | RECOMMENDED(共同前提) |
| [01-web-clipping](01-web-clipping.md) | 网页剪藏 | READY(PoC 已实跑) |
| [02-web-snapshots](02-web-snapshots.md) | 网页快照 | READY(条件:配额先落地) |
| [03-api-sources](03-api-sources.md) | API 来源(JMESPath→Atom→FreshRSS) | READY |
| [04-email-newsletters](04-email-newsletters.md) | 邮件简报(outbound+inbound) | CONDITIONAL(SMTP 前置) |
| [05-bookmarks](05-bookmarks.md) | 书签 | READY |
| [06-obsidian-library](06-obsidian-library.md) | Obsidian 只读集成 | READY |
| [07-workspaces](07-workspaces.md) | 工作区(ItemRef 集合) | READY |
| [08-library-views](08-library-views.md) | 稍后读/收藏/搜索统一 | READY |
| [09-rag-index](09-rag-index.md) | RAG 索引(sqlite-vec) | READY |
| [10-agent-workbench](10-agent-workbench.md) | Agent 工作台 | READY |
| [11-tags-graph](11-tags-graph.md) | 标签与图谱 | READY |
| [12-phase2-ui-architecture](12-phase2-ui-architecture.md) | UI 总体设计 | RECOMMENDED |
| [13-implementation-roadmap](13-implementation-roadmap.md) | 依赖图与实施顺序 | — |

配套研究报告(本目录之外):
- `docs/research/ai-feeds-40.md` — 40 个真实 AI RSS 源验证与接入
- `docs/research/performance-after-40-feeds.md` — 扩容后性能基准
- `docs/research/local-translation.md` — 本地翻译根因与方案

## PoC 代码位置(不入生产 bundle)

`research/phase2-pocs/` — 每个子目录可独立运行,命令见各报告 §20;
`artifacts/backups/` 含本轮 FreshRSS 变更前后 OPML 与 Lumi 备份。
