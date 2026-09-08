# FOLO_COMPARISON.md — 指定 Folo 分支与 LumiRSS 对比

> 对象：https://github.com/Guyungy/Folo （**不是** RSSNext/Folo 官方主仓库）
> 分支 `dev`，HEAD `73a77e59dca560c7129e39959ddfc5c2d1647d94`（2026-09-07），AGPL-3.0
> 工作目录：`/home/zephyr/projects/research/Folo`（仓库外，浅克隆）
> 详细证据：`/home/zephyr/projects/research/reports/folo-research.md`（含全部代码路径）
> 方法：静态只读分析。**未运行 Folo、无任何性能实测数据**——下文"性能"一节全部是静态推断，与实测数据明确分列。

## 0. 分支与上游关系

- fork 基点 ≈ 上游 RSSNext/Folo `b835efa0`（2026-09-02，桌面 v1.13.0）；其上仅 **8 个自有提交**（2026-09-06~07）。
- 增量核心：约 1600 行的 `apps/server` 本地数据/AI 服务（Hono + `node:sqlite`，零端口，主进程内嵌）+ Electron IPC 接线 + 去登录（mock 本地会话）。
- `apps/server/LOCAL_STATUS.md` 采用"宣称已实现 / 唯一验证声明 / 剩余工作"三段式，**未发现 README 夸大**；作者自认：AI 真实 provider、安装级备份恢复、图片/PDF 附件、AI memory、托管依赖（push/telemetry/image proxy）审计均未完成。
- 教训（正面）：这种"宣称/验证/剩余"的就绪度文档值得 LumiRSS 报告借鉴。

## 1. 功能矩阵（Folo 状态 → LumiRSS 对照）

状态：✅已实现并验证 / 🟡已实现未运行验证 / 🟠部分 / 🟨界面或占位 / ❌缺失。

| 功能 | Folo(指定分支) | 证据 | LumiRSS（本仓） | 差异与建议 |
|---|---|---|---|---|
| 订阅管理 | ✅（本地 SQLite，有测试） | `apps/server/src/app.ts` `/subscriptions` + `app.test.ts` | ✅ FreshRSS 真源（0013） | 架构不同：Folo 本地库 vs Lumi FreshRSS 单一真源；不建议引入影子 RSS 后端 |
| OPML 导入/导出 | 🟨 本地版不可用（走托管端点，本地 404）；旧库导入仅 CLI | `DiscoverImport.tsx` vs `app.ts` 无路由 | ✅ OPML 导入导出（0013，真实 FreshRSS） | LumiRSS 完整 |
| RSSHub 集成 | ✅ `rsshub://` 协议 + 实例配置（有测试） | `rss.ts:fetchFeedDocument/setRSSHubBaseURL` | ✅ + 本任务新增自动识别/凭据/env 应用链（9228256） | LumiRSS 控制面更完整；Folo 的"逐候选失败原因聚合"值得借鉴 |
| 阅读状态 | ✅ set 语义 + 全部已读（有测试） | `/reads` `/reads/all` | ✅ set 语义（0004，e2e 守护） | 一致 |
| 收藏/稍后读 | ✅ collections（有测试） | `/collections` | ✅ 收藏 + 本地稍后读（0011） | LumiRSS 多"稍后读"本地层 |
| 过滤规则 | 🟠 UI/单测齐全但本地无持久化路由 | `action/store.test.ts` vs 无 `/actions` 路由 | ✅ 显示层过滤规则（0017+，本地持久化） | LumiRSS 更完整 |
| 搜索 | 🟡 Fuse.js 本地索引 + Cmd+K | `store/search/index.ts` | ❌ 站内搜索缺失 | **可复用候选**（fuse.js，MIT）→ P1 |
| 长列表 | 🟡 react-virtual + masonic 瀑布流 | `entry-column/index.tsx` | 🟠 分页游标（0004）+ 快速选择优化；未见虚拟化 | **可复用候选**（@tanstack/react-virtual）→ 长列表卡顿时 P1 |
| 正文提取 | 🟡 主进程 readability + DOMPurify | `packages/readability` | ❌ | 可借鉴（@mozilla/readability MIT） |
| 媒体 | 🟠 渲染全、本地新抓 feed 无附件数据 | `rss.ts:refreshFeed` | 🟠 按条目 contentHtml 内联媒体 | 相当 |
| 排版设置 | 🟡 上游继承（atomWithStorage） | `defaults.ts` | ✅ 深度定制（0012/0017：字号/行距/段距/宽度/对齐/缩进/背景/预设/自定义 CSS/字体导入） | LumiRSS 更完整 |
| 翻译 | 🟡 代码完整，真实 provider 未验证 | `/ai/translation` +NDJSON 批量 | ✅（本任务 d3cf014：分块双语/仅译文/本地引擎/统一设置） | 本次后 LumiRSS 领先 |
| AI 摘要/对话 | 🟡 有测试（流式 delta、上下文注入），真实 provider 未验证 | `app.test.ts` 用例 5 | ✅（0015-0017，mock 验证） | 相当；Folo 的"摘要本地抽取式回退"思路可借鉴 |
| TTS/转录 | 🟡 | `/ai/tts` `/entries/transcription` | ❌ | 可选路线 |
| 备份恢复 | 🟠 应用内仅导出客户端缓存库；主库无应用内备份 | `db.desktop.ts:exportDB` | ✅ 完整（0018 + 本任务 c8a1bcc：能力预检/一致快照/离线恢复/隔离栈实测） | **LumiRSS 显著领先** |
| 同步 | ❌（设计意图） | README | N/A（FreshRSS 承担） | — |
| 移动端 | ❌（本地版范围外） | 仅 macOS 桌面 | ✅ PWA + 移动五屏（0007/0011） | LumiRSS 领先 |

## 2. 性能（静态推断 vs 实测，严格分栏）

**实测：无。** Folo 未构建/未运行（缺图形环境与构建依赖代理拉取受限）；LumiRSS 侧的性能回归数据见 VALIDATION.md。两项目没有可比的同条件实测数据，不做跨项目排名。

静态推断（Folo）：
- 渲染：长列表全面虚拟化（react-virtual 单列 + 双轴网格 + masonic 瀑布流）；无 React Compiler；手写 memo 少；细粒度选择器订阅。
- 状态：Jotai（UI 原子）+ Zustand（领域模型，immer/persist）+ TanStack Query 三层。
- 请求：去重/缓存交给 TanStack Query；批量合并 batshit；流式 NDJSON/SSE 自研小工具；AbortSignal 全链贯通。
- SQLite：node:sqlite 同步 API + WAL + prepared statement（主进程）；`/reads/all` 逐行 INSERT 与 articleContext 多行扫描在万条级是潜在慢点（静态推断）。
- 依赖：renderer 101 个运行时依赖（lexical/shiki/firebase/motion 等），前端包体偏大；Node 数据服务极轻。

对照（LumiRSS 静态）：条目列表未虚拟化（游标分页 + content-visibility 需核实），状态单层 Zustand + TanStack Query，依赖面小。**推断**：万条级长列表滚动 LumiRSS 可能吃亏（无虚拟化）；首屏/包体 LumiRSS 占优（依赖少）。这属于静态推断，须实测验证后才能作为决策依据。

## 3. 可复用清单（许可证已修正）

**许可证修正**：调研报告按"LumiRSS=MIT"给结论，实际 LumiRSS 是 **AGPL-3.0**（根 LICENSE）。Folo 整仓同为 AGPL-3.0 → **同许可下源码级复用是许可兼容的**（需保留版权与许可声明，登记 THIRD_PARTY_NOTICES.md）。但维护成本原则不变：只在收益/成本比明确时移植小型纯模块，且不得引入 Electron/上游服务耦合。

| 模块 | Folo 路径/符号 | 复用判定 | LumiRSS 接入点 | 收益/成本 |
|---|---|---|---|---|
| 虚拟化列表选型 | `entry-column/index.tsx`（@tanstack/react-virtual） | 依赖复用（MIT），模式参考 | `EntryList` | 长列表卡顿时的首选方案；先实测确认瓶颈 |
| 本地搜索 | `store/search`（fuse.js + cmdk） | 依赖复用 + 模式参考 | 新增：条目内搜索 | P1 新功能 |
| 批量请求合并（batshit 模式） | `translation/store.ts` | 借鉴思路（我们已用服务端批量+锁实现等效） | ai_translation_segments | 已覆盖 |
| 就绪度文档写法 | `apps/server/LOCAL_STATUS.md` | 文档模式借鉴 | 任务/milestone 报告 | 零成本 |
| SSE→UI-chunk、IPC 流桥、fetch 拦截 | `ai.ts:streamCompletion` 等 | 不复用（Electron/IPC 场景不存在于 LumiRSS BFF 架构） | — | — |
| RSS 数据库/本地订阅引擎 | `apps/server/src/db.ts` | **不复用**（会破坏 FreshRSS 单一真源——架构红线） | — | — |
| 云账户/遥测/受限品牌资源 | firebase、tracker、icons/mgc | 不复用 | — | — |

依赖选型清单（均为常见 MIT/Apache，可平移）：`fuse.js`、`@tanstack/react-virtual`、`tinykeys`、`react-hotkeys-hook`、`@mozilla/readability`、`fast-xml-parser`。
