# Roadmap

> 只回答"接下来准备做什么"。已完成的工作与版本化发布记录在仓库根
> [CHANGELOG.md](https://github.com/paidethon/LumiRSS/blob/main/CHANGELOG.md)；
> 逐项任务状态以机读台账 `docs/implementation-status.json` 为准
> （220 项，`npm run check:dashboard` 漂移守卫，看板接法见
> [operations](/operations) §项目进度看板）。

## Current state（2026-09）

MVP（0000–0020）、Phase 2 知识工作台、Phase 2 recovery 返工、2.0.0
邀请制多账户与默认关闭的可选公开注册均已合入 main 并部署生产。3.0.0
重建批次在此之上小步补齐（用户视角明细见 CHANGELOG）：来源中心九类
汇总、Obsidian 服务端受限导出、AI 日报、邮件简报内容页、RAG 索引
内容页、OPML 导入 RSSHub 自动匹配、内置 8 款开源阅读字体、49 项用户
偏好上云、单容器拓扑；认证以应用会话为主，basic auth 转为兼容可选项。
机读功能清单见 `docs/feature-manifest.json`（126 条）；FreshRSS/RSSHub
上游全功能对照见 [upstreams](/upstreams) 与
`docs/public/reference/upstream-feature-matrix.html`。

## Next（候选，立项由用户批准的 spec 决定）

- Agent 消息 / RAG 端点的 Web 侧本地 interface 迁移到生成 schema 别名
  （response_model 已补齐，剩余为 Web 消费端重构）；
- 剪藏/快照阅读体验打磨；
- 来源运维 UI 的 J4 类合并契约回归排查（ny1/nx1 批次）。

## Explicitly deferred / rejected {#deferred}

- WebDAV vault、Bergamot 本地翻译（无中文模型）、外部向量库服务
  （sqlite-vec 单文件已够）、多模型自动路由；
- 多租户形态、公共互联网硬化（邀请制小规模多账户与默认关闭的可选公开
  注册已实现，见 [architecture](/architecture#accounts)；对公网开放前的
  加固仍不在范围内）；
- PWA Push / 后台同步（app-shell 离线缓存已实现；其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、公开 Profile、奖励经济；
- 原生移动 App；
- OAuth；
- Kubernetes、Redis / Celery（除非真实压力证明）；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [architecture](/architecture#search)）。

## 验收原则

- 用户无需日常进入 FreshRSS / RSSHub；原生 RSS 和 RSSHub Feed 都可
  发现、添加和阅读；
- read / starred 与 FreshRSS 一致（set 语义；打开不自动标读）；
- 主题与阅读偏好可用且可持久化；AI 可关闭、未配置时诚实呈现、失败
  不影响阅读；
- 手机可舒适使用；加载/空/错误状态完整；服务重启后数据存在；
  backup / restore 经过真实演练；
- DOMPurify 边界与行为回归测试保持绿色；
- 新 Agent 只读 Git 仓库（AGENTS.md → 相关 docs → 源码/测试）即可
  理解项目。
