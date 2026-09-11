# LumiRSS Documentation

LumiRSS 是一个单用户、自托管、source-first 的信息阅读器：FreshRSS 作为
RSS 域引擎与真源，RSSHub 生成非 RSS 来源，项目自有的 FastAPI BFF 与
React Web / PWA 客户端。

项目阶段：**Phase 2 知识工作台**（MVP 0000–0020 已完成；phase2
integration 分支按 [ROADMAP.md](ROADMAP.md) 与
[research/phase2/](research/phase2/README.md) 推进）。已完成工作见
[history/milestones.md](history/milestones.md)。

首次接触本项目：先读根目录 [README](../README.md)，再按
[getting-started.md](getting-started.md) 跑起来。

## 我要做什么 → 读什么

| 你要做什么 | 读什么 |
|---|---|
| 本地跑起来 / 自托管快速上手 | [getting-started.md](getting-started.md) |
| 部署 / 升级 / 回滚 / 运维 | [how-to/deploy.md](how-to/deploy.md) |
| 备份 / 恢复 / 灾难恢复 | [how-to/backup-restore.md](how-to/backup-restore.md) |
| 排查故障 | [how-to/troubleshoot.md](how-to/troubleshoot.md) |
| 查配置键含义 | [reference/configuration.md](reference/configuration.md) |
| 跑测试 / CI 门禁 | [reference/testing.md](reference/testing.md) |
| 理解系统架构（数据流 / 边界 / 不变量） | [explanation/architecture.md](explanation/architecture.md) |
| 搞懂全局搜索原理 | [explanation/search.md](explanation/search.md) |
| 复用 vs 自研边界 / 生成物规则 | [explanation/reuse-policy.md](explanation/reuse-policy.md) |
| 关键架构决定（ADR） | [decisions/](decisions/) |
| 改 UI / 视觉与交互 | [design/design-system.md](design/design-system.md)（背景：[design/README.md](design/README.md)） |
| 产品范围与原则 | [product/PRD.md](product/PRD.md) |
| 许可证 / 上游引用 | [upstream/](upstream/)（[LICENSE_AUDIT.md](upstream/LICENSE_AUDIT.md)） |
| 查历史里程碑 / 发布记录 | [history/milestones.md](history/milestones.md) |

## 阅读纪律

- 每个事实只在一个活跃文档维护，其他文档链接过去；
- 日常开发只读本文件 + 当前任务相关文档，不要预载历史里程碑、完整 PRD
  或上游研究；
- 改数据路径 / API / 边界时读 [explanation/architecture.md](explanation/architecture.md)
  与相关 ADR；改契约/生成物时读
  [explanation/reuse-policy.md](explanation/reuse-policy.md)。
