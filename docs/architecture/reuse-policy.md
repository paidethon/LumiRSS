# Build vs Reuse — source-of-truth boundaries

> 长期有效的复用/边界策略（Post-0020 dedup refactor 落地）。回答三个问题：
> 这段代码为什么存在？谁是这个数据/行为的真源？为什么 Lumi 必须自己维护它？

新增基础设施（协议客户端、schema、overlay 行为、代码生成）之前，先查这张表：
上游/框架已拥有的职责，不要再在 Lumi 里长出第二份实现；Lumi 只保留真正的
产品策略与安全边界。

## Source of Truth Matrix

| Domain | Source of truth | 说明 |
| --- | --- | --- |
| RSS entries / read / star | FreshRSS | Lumi SQLite 永不 shadow-copy RSS 域数据 |
| non-RSS feed 生成 | RSSHub | 上游 generator，不是 entry 数据库 |
| 订阅 / 分类存储 | FreshRSS | OPML 导出即 FreshRSS 自己的 `subscription/export` 代理 |
| 公开 API 契约 | FastAPI / Pydantic | 所有路由带 `response_model`；改契约=改模型 |
| Web API 类型 | 生成物（`pnpm api:generate`） | `apps/web/src/api/generated/schema.ts`，types.ts 只是领域别名层 |
| server 可持久化 settings | Pydantic `PortableSettings` | 前端默认值/枚举/边界消费生成的 `settings-meta.ts` |
| curated RSSHub 路由暴露 | Lumi policy（`rsshub.py CATALOG`） | 上游事实用 pinned 快照校验（见下） |
| RSSHub 配置项 schema | Lumi curated allowlist | 上游无稳定机器可读 schema（KEEP，见下） |
| overlay / a11y 行为 | Base UI（`@base-ui/react`） | 只允许在 `components/ui/` 内 import |
| 服务器状态缓存 | TanStack Query | query keys / invalidation 集中在 `api/queries.ts` |
| Lumi 视觉 tokens | Lumi Design Tokens（`--lumi-*`） | 语义 token，不硬编码颜色 |
| AI 派生缓存（summary/translation/conversation） | Lumi SQLite | 共享机制在 `ai_artifacts.py`，规则不重复实现 |
| secrets | 服务端 SecretStore（0600 JSON） | 永不进浏览器、永不入库/备份 |
| 设备本地 UI 状态 | Web（localStorage） | 见下方 read-later 条目 |

## Generated artifacts（生成物一览）

| 生成物 | 生成来源 | 命令 | Drift 检查 |
| --- | --- | --- | --- |
| `apps/web/src/api/generated/openapi.json` | FastAPI `app.openapi()` | `pnpm api:generate` | `pnpm api:check`（CI 同） |
| `apps/web/src/api/generated/schema.ts` | openapi-typescript | `pnpm api:generate` | 同上 |
| `apps/web/src/api/generated/settings-meta.ts` | `PortableSettings`（Pydantic） | `pnpm settings:generate` | `pnpm settings:check`（CI 同） |
| `services/bff/src/lumirss/rsshub_routes.generated.json` | pinned RSSHub 镜像内 `routes.json` | `services/bff/scripts/export_rsshub_routes.py` | `tests/test_rsshub_catalog_upstream.py`（快照↔compose digest 一致性 + 目录↔上游路由校验） |

规则：

- 生成文件头部必须带 `AUTO-GENERATED — DO NOT EDIT`；不要手改生成物。
- 每个生成物必须有确定性 generator 与 drift 检查（CI 已接入 api/settings 两项；
  RSSHub 快照由 digest 断言与测试覆盖，重新生成需要本地 docker）。
- 改契约/改 settings 的流程永远是：改 BFF 模型 → 重新生成 → 消费编译错误/测试驱动修 Web。

## Python 静态防护

`services/bff` 使用 ruff（`F/E/W/I/UP/B/SIM`；E501 因历史无行宽约定而暂缓）。
F811 会阻止「同一 class 里重复定义方法」这类曾经真实发生的静默覆盖 bug。
SQL 语句一律内联字面量写在 execute 调用处——项目的静态安全工具会拒绝
任何间接引用的 SQL，这是一条有意的仓库约定。

## KEEP — justified（审查后有意保留的自研实现）

这些实现「看起来像轮子」，但替换不如保留：

- **WebDAV 客户端（`webdav.py`）**：自研 thin 协议层（~355 LOC）承载了
  大量安全属性——TLS verify 开关、origin-pinned redirects、有界读取、
  `dir_fd` 打开与 0600 权限、路径禁越（`..` 拒绝）、全量错误脱敏。
  通用 WebDAV 库（如 webdav4）无法按需提供这些约束，引入库只会把
  安全策略分散到适配层。安全属性是 Lumi 的产品职责，不是"协议轮子"。
- **AI provider transport（`ai_provider.py`）**：单一 OpenAI-compatible
  `POST /chat/completions`（~69 LOC），自定义 base_url、稳定错误分类、
  MockTransport 可测。OpenAI SDK / LiteLLM 等为这一条 HTTP 调用引入
  重量级依赖不值得；未来 streaming 需求出现时再评估。
- **RSSHub 配置项 schema（`rsshub_control.py SCHEMA`）**：RSSHub 没有
  版本化、机器可读的配置元数据；这份 curated allowlist（key/边界/
  分组/是否 secret）本身就是 Lumi 的安全策略。有意的 curated 边界。
- **PaneSeparator（`components/ui/PaneSeparator.tsx`）**：94 LOC，含
  ARIA separator、键盘 ±10px、双击重置、与 settings store 的持久化接线。
  `react-resizable-panels` 为此引入依赖不划算；Base UI 也无对应原语。
- **read-later（稍后读，`store/read-later.ts`）**：当前定义为设备本地
  产品数据（localStorage），刻意不映射 FreshRSS starred（收藏≠稍后读）。
  跨设备同步是明确的 roadmap 项，落地时应迁到 Lumi SQLite 而非浏览器
  之外的第三方存储。
- **EntryRow / EntryCard 双组件**：桌面行/移动卡片的形态分裂是有意的
  响应式策略（同时渲染、CSS 隐藏切换），合并会付出可视化回归的高风险。
  共享逻辑（动作、选中态、时间格式化）已分别下沉到
  EntryActionButtons / useReaderUi / date-format。

## 反模式（不许再长回来）

- Feature 组件直接 import `@base-ui/react`（必须经 `components/ui/`）。
- 手写 BFF 响应 DTO、手抄 settings 默认值/边界/枚举。
- 在 Web 里拼 BFF 之外的第二条 HTTP 通道（`api/client.ts` 是唯一出口；
  keepalive 例外见 `store/settings-sync.ts` 注释）。
- 新增"第二个 headless UI 库"、为几十行代码引入大依赖、
  或把"调研过"的库留在依赖清单里。
