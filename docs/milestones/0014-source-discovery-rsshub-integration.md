# 0014 — Source Discovery & RSSHub Integration

> Status: **Completed** · Branch: `feat/0014-source-discovery-rsshub`
> Created by Gate 0 (2026-09-01) from baseline `26faaed` (main, 0013 merged).
> Completed by Final Gate (2026-09-01).

## Goal

用户可以从两类入口出发，在 Lumi 内完成「发现 → 配置 → 预览 → 订阅」：

```text
A. 普通网站 URL → 发现 RSS/Atom 候选 → 预览 → 订阅
B. RSSHub 支持的路由 → 参数配置 → 生成 feed → 预览 → 订阅
```

最终订阅的 feed 依然属于 FreshRSS（唯一 source of truth）。

## User outcome

订阅中心「添加订阅」对话框扩展为三种模式（RSS/Atom 直填、网站发现、
RSSHub 路由）；发现出的候选 feed 复用 0013 的 preview → subscribe
管道，无需打开 FreshRSS UI。

## Baseline（2026-09-01，main @ 26faaed）

0013 已交付并合并：

- `POST /api/v1/feed-preview` + `POST /api/v1/subscriptions` pipeline；
- `FeedPreviewService` safe-fetch boundary（URL/DNS/逐 IP 校验、bounded
  2 MiB、bounded redirects ≤5 跳逐跳重验证、离线 feedparser 解析）；
- `FreshRSSControlAdapter`（subscribe / list_subscriptions / 分类管理）；
- Web `AddSubscriptionDialog`（仅直接 RSS/Atom）+ `SubscriptionsPage`
  订阅中心；`useSubscribeMutation` + `invalidateSubscriptionState`；
- docker-compose：RSSHub `127.0.0.1:1200`（0008 引入，`http://rsshub:1200`
  为 FreshRSS 容器内视角）。

0013 明确 defer 到 0014：website → RSS discovery（rel=alternate /
常见路径猜测）、RSSHub route discovery / catalog / 参数表单。

## Architecture invariants（全 milestone 生效）

```text
Native RSS / Atom ───────────────────────────┐
                                             ▼
Non-RSS source → RSSHub → FreshRSS
                                             ▼
                                    FreshRSSAdapter / ControlAdapter
                                             ▼
                                       FastAPI BFF
                                             ▼
                                        React Web
```

- FreshRSS 是 RSS domain 唯一 source of truth；Lumi SQLite 不建
  subscriptions/feeds/articles 影子库；
- 浏览器只访问 `/api/v1/*`，绝不直连 FreshRSS / RSSHub；
- RSSHub 是 upstream feed generator：Lumi 只构造路由、经 BFF 预览，
  FreshRSS 负责抓取存储；
- RSSHub 路由构造与预览全部 server-side（BFF 使用服务端配置的
  `RSSHUB_BASE_URL`）；浏览器侧 0010a 的实例列表仅作 UI 管理，不参与
  0014 的构造/预览（防浏览器注入任意 base URL → SSRF）；
- TanStack Query 拥有订阅 server state；Zustand 只拥有 UI/navigation；
- 发现出的候选 feed 走 0013 既有 `POST /feed-preview` +
  `POST /subscriptions` → FreshRSS，不建第二套 subscribe 通道；
- 现有阅读路径（feeds/entries/entryRef/cursor/subscriptionRef）零破坏；
- 外部 HTML/RSS 均 untrusted：safe-fetch 边界 + 离线解析 + DOMPurify
  （文章渲染）不变。

## Blocking scope

1. **Website → RSS discovery**：safe-fetch 网页 → 提取 `<link
   rel="alternate">` RSS/Atom 候选（相对 URL 安全解析、去重）；无声明
  候选时按序探测 5 个常见端点（/feed、/rss、/rss.xml、/atom.xml、
  /feed.xml），首个成功即停。不爬站、不递归、不做 DOM 提取。
2. **RSSHub 路由目录 + 参数配置**：Lumi-owned 静态精选 catalog
   （route id / 标题 / 描述 / path template / 参数描述符）；server-side
   构造与校验（required/pattern/URL 编码/路径注入防护）；
   `POST /api/v1/rsshub/preview` 经 BFF 预览生成 feed。
3. **订阅中心集成**：`AddSubscriptionDialog` 演进为 `AddSourceDialog`
   （三种模式），预览/订阅复用 0013 管道；不新建第二个管理入口。

## Non-goals

generic scraping / CSS selector 解析、任意 HTML 提取规则、JSON/API
来源、WordPress API、browser automation、AI 发现/推荐、global search、
source marketplace、multi-user registry、email newsletter、Obsidian、
web clipping、RSSHub 完整路由集 vendoring、RSSHub 文档运行时抓取、
Redis/Celery、Lumi SQLite 存 RSS 数据。

## Decisions（Gate 0）

1. **RSSHub base URL 是服务端配置，不是浏览器实例列表**：新增
   `RSSHUB_BASE_URL`（BFF 预览可达）+ 可选 `RSSHUB_FRESHRSS_BASE_URL`
   （FreshRSS 容器视角可达，默认同 BASE_URL）——0008 已实测
   `127.0.0.1:1200`（宿主机视角）≠ `http://rsshub:1200`（容器视角）。
   feedUrl（交 FreshRSS 抓取的 URL）用 FRESHRSS 视角构造。
2. **RSSHub catalog 为 Lumi 静态精选集**（不 vendor RSSHub、不运行时
   抓文档）；Gate 6 对本地实例逐条实测，只保留真实可用路由。
3. **发现 API 形状**：`POST /api/v1/source-discovery`（404
   `no_feed_discovered`）、`GET /api/v1/rsshub/routes`、
   `POST /api/v1/rsshub/preview`（响应形状与 feed-preview 一致：
   title/feedUrl/description/format/alreadySubscribed）。
4. **探测策略**：声明候选优先（不逐个预取，preview 阶段验证）；
   无声明候选才按序探测常见端点，首个解析成功即停（≤5 次 bounded
   fetch）。
5. **RSSHub 预览安全**：固定 operator 配置 base origin；重定向每跳
   校验，只允许同 origin（scheme+netloc 完全一致）；bounded 2 MiB /
   timeout 复用共享 client；离线解析复用 `parse_feed_document`。
6. **Web UI**：`AddSourceDialog` 三 tab 单表面，替代
   `AddSubscriptionDialog`（直接 RSS/Atom 逻辑原样迁移）；预览与订阅
   复用 `useFeedPreviewMutation` / `useSubscribeMutation`。

## API

```text
POST /api/v1/source-discovery        {url} → {candidates:[{feedUrl,title,source,format}]}
GET  /api/v1/rsshub/routes           [RssHubRouteDescriptor]
POST /api/v1/rsshub/preview          {routeId,params} → FeedPreview 形状
```

新增稳定错误：

```text
invalid_source_url(400) · no_feed_discovered(404) · rsshub_not_configured(503)
rsshub_route_not_found(404) · rsshub_invalid_parameters(400) ·
rsshub_fetch_error(502)；复用 unsafe_feed_url / feed_fetch_error /
feed_too_large / not_a_feed / invalid_feed_url
```

## Acceptance criteria

- [ ] 网站 URL → 候选发现（声明 + 有界探测）→ 预览 → 订阅闭环；
- [ ] RSSHub 路由选择 → 参数表单（required/optional、校验）→ 预览 → 订阅；
- [ ] 失败流：invalid URL / no feed / RSSHub 未配置 / 缺参数 / 上游错误 /
      重复订阅 均有诚实 UI 状态；
- [ ] 订阅经 FreshRSS server-confirmed，invalidate 后订阅列表/侧栏同步；
- [ ] 桌面 + 移动布局可用；a11y（键盘/焦点/Escape/44px/reduced motion）；
- [ ] BFF/Web 全量测试 + lint + build 通过；真实运行时 smoke 验证。

## Gate breakdown

```text
Gate 0 — 基线 + Spec + 分支（本文件）
Gate 1 — Discovery 域契约（DTO/错误映射/路由骨架）+ 聚焦测试
Gate 2 — Website → RSS discovery（safe-fetch 复用 + rel=alternate + 探测）
Gate 3 — RSSHub catalog + 参数构造 + preview
Gate 4 — 发现 → 订阅管道接线（Web hooks + 复用 0013 mutation）
Gate 5 — AddSourceDialog（三模式）+ 订阅中心集成 + Web 测试
Gate 6 — 真实运行时验证（docker compose + 实测路由 catalog 校准）
Gate 7 — 架构/安全复审（git diff main...HEAD）
Final — 全量验收 + 文档收口 + 最终 commit
```

## Gate Progress

### Gate 0

Status: Completed (2026-09-01)

- 基线：main @ `26faaed`（0013 已合并），working tree clean；
- 创建分支 `feat/0014-source-discovery-rsshub`；
- 创建本 milestone 文档；docs/README + ROADMAP 激活 0014；
- Agent Hub 能力：OpenCode 全局配置（备份后）注册 design-review /
  architecture-visualization skill 目录引用 + Playwright MCP
  （`npx @playwright/mcp@latest`）；配置需重启生效，本 run 以直接读
  SKILL.md 方式按需参考。

### Gate 1 + 2

Status: Completed (2026-09-01)

Implemented:

- `feed_preview.py` 安全边界重构为可复用：`safe_fetch`（返回
  `FetchedDocument{body, final_url, content_type}`）、`read_bounded_body`
  public、`MAX_FEED_BODY_BYTES` 公共常量；`FeedPreviewService` 行为不变；
- 新增 `source_discovery.py`：
  - `POST /api/v1/source-discovery`（非变更；不持有任何 FreshRSS
    引用——read-only by construction）；
  - rel=alternate 声明提取（stdlib HTMLParser，不联网）：type 判定、
    typeless feed-ish href 兜底、相对 URL 按最终跳转地址解析、
    凭据/malformed href 跳过、fragment 不敏感去重、上限 20；
  - 直接 feed URL 粘贴 → 单候选直返；
  - 无声明候选才按序探测 5 个常见端点（/feed /rss /rss.xml /atom.xml
    /feed.xml），首个解析成功即停（bounded，无爬站）；
  - 非 HTML content-type 不做链接提取与探测；
  - 错误：`invalid_source_url`(400) / `no_feed_discovered`(404)，复用
    unsafe_feed_url / feed_fetch_error / feed_too_large；
- 测试 `test_source_discovery.py`（28 cases，全部 mock 网络）。

### Gate 3

Status: Completed (2026-09-01)

Implemented:

- `config.py` 新增 `RssHubSettings`：`RSSHUB_BASE_URL`（BFF 预览可达，
  允许内网/loopback——operator 配置非用户输入）+ 可选
  `RSSHUB_FRESHRSS_BASE_URL`（FreshRSS 容器视角，默认同 BASE_URL；
  0008 已实测 127.0.0.1:1200 ≠ http://rsshub:1200）；结构校验
  （http/https、无凭据/query/fragment、无路径）；`.env.example` 文档化；
- 新增 `rsshub.py`：
  - Lumi-owned 静态精选 catalog：14 条路由（全部对本地 pinned
    RSSHub 实例逐条实测 200 + 可解析，2026-09-01 校准；不 vendor
    RSSHub、不运行时抓文档）；
  - `build_path`：required 校验 + regex fullmatch + 逐段 URL 编码 +
    结构校验（无 `//` / 空段 / `..`）——路径注入不可能；
  - `RssHubService.preview`：base+path 有界抓取（2 MiB、共享 client
    超时），重定向逐跳校验必须留在配置 origin 内（scheme+netloc
    一致），离线解析复用 `parse_feed_document`；
    feedUrl 用 FreshRSS 视角 base 构造（订阅后由 FreshRSS 抓取）；
    alreadySubscribed 只读比较（control adapter 只读）；
  - 错误：rsshub_not_configured(503) / rsshub_route_not_found(404) /
    rsshub_invalid_parameters(400) / rsshub_fetch_error(502)；非 feed
    复用 not_a_feed；
- 路由：`GET /api/v1/rsshub/routes`（`{configured, routes}`）、
  `POST /api/v1/rsshub/preview`（响应形状与 feed-preview 一致）；
- 测试 `test_rsshub.py`（34 cases）+ settings 校验用例。

### Gate 4 + 5

Status: Completed (2026-09-01)

Implemented:

- Web API 层：`discoverFeeds` / `getRssHubRoutes` / `previewRssHub` +
  types + hooks（discovery/preview 为无副作用 mutation，不 invalidate；
  routes 为 query，enabled 门控）；
- `management-errors.ts` 扩展 0014 全部稳定错误文案（含 0013 预览
  错误收敛于此，删除 AddSubscriptionDialog 本地副本）；
- `AddSourceDialog`（三模式单表面，取代 AddSubscriptionDialog）：
  - tablist（←/→ 键盘导航、aria-selected）+ tabpanel；
  - `DirectFeedTab`：0013 逻辑原样迁移（input id/label/文案不变，
    网页 URL 本地提示指向网站 tab）；
  - `WebsiteTab`：发现 → 候选 radiogroup（默认选首）→ 预览 →
    PreviewStage；错误/加载/无结果状态齐全；重新选择；
  - `RssHubTab`：目录 + 搜索 → 参数表单（required 标记/help/example、
    本地 pattern 即时反馈，服务端兜底）→ 预览 → PreviewStage；
    未配置 → 诚实横幅（不渲染假目录）；
  - `PreviewStage`：三种模式共享的 metadata 卡片 / 已订阅提示 /
    真实分类 / 确认添加 / 成功状态（复用 useSubscribeMutation →
    invalidateSubscriptionState，不建第二套订阅逻辑）；
  - busy 关闭防护：各 tab 通过 registerGuard 注册（提交中 Escape/
    遮罩不关闭）；
- `SubscriptionsPage`：入口改「添加来源」；设置中心：来源发现
  说明入口（去掉 0014 planned 占位）、RSSHub 状态 plannedFor → 0018、
  RSSHub 设置页文案诚实化（实例清单不参与 0014 构造）；
- 测试：新增 `source-discovery.test.tsx`（12）、`rsshub-add.test.tsx`
  （12）；迁移/更新 add-subscription（14）、gate-b、gate4-pages、
  subscription-management。

### Gate 6

Status: Completed (2026-09-01)

- 重启本地 dev BFF（当前代码 + RSSHUB_BASE_URL=http://127.0.0.1:1200
  + RSSHUB_FRESHRSS_BASE_URL=http://rsshub:1200）；
- 真实 RSSHub + 真实 FreshRSS live smoke（12/12 PASS）：
  - routes catalog configured=true + 14 路由；
  - preview hackernews / github-starred-repos（DIYgod）→ 200 真实
    metadata，feedUrl = http://rsshub:1200/...（容器视角）；
  - 缺参 / 路径注入 / 未知路由 → 稳定 400/404；
  - 订阅 E2E：subscribe 201 → subscriptions 列表可见 → unsubscribe
    204 → 基线还原（无残留数据）；
  - vite 代理路径：`5173/api/v1/rsshub/routes` → configured=true
    + 14 路由（浏览器可见面验证）；
- 环境限制：宿主机 DNS 为 TUN fake-IP（198.18.0.0/15），website
  discovery 对公网站按设计被 SSRF 边界拦截（400 unsafe_feed_url，
  实测）；成功路径由 28 个离线测试覆盖（与 0013 Gate 5 同一已知
  环境限制）；
- 浏览器 UI 实机点击验证：本 run 无可用浏览器工具（Playwright MCP
  配置已持久化，重启后可用）；UI 由 38 个 DOM 级测试 + 响应式
  Dialog primitive 覆盖，web app index 200。

## Completion notes

> 收口于 Final Gate（2026-09-01）。

### Scope audit（Acceptance 逐项）

Implemented:

- 网站 → RSS/Atom 发现：safe-fetch 复用（SSRF 边界）、rel=alternate
  提取、相对 URL 解析、去重、常见端点有界探测（首个成功即停）；
- RSSHub 目录 + 参数配置：14 条实测校准的 Lumi 静态路由、required/
  pattern 校验、server-side 构造与预览、FreshRSS 视角 feedUrl；
- 订阅中心三模式 AddSourceDialog（RSS/Atom + 网站 + RSSHub），
  预览/订阅复用 0013 管道（无第二套订阅逻辑）；
- 失败流：invalid URL / no feed / RSSHub 未配置 / 缺参 / 上游错误 /
  重复订阅均有诚实文案（management-errors 统一映射）；
- a11y：tablist 键盘导航、busy 关闭防护（Escape/遮罩）、44px 触控、
  label 关联、radiogroup 候选选择；
- 桌面 + 移动复用同一 Dialog primitive（fullscreenOnMobile）。

Deferred / known limitations:

- 浏览器实机点击验证：本 run 无浏览器工具（Playwright MCP 配置已
  持久化，重启 OpenCode 后可用）；UI 行为由 40 个 DOM 级测试覆盖；
- 宿主机 fake-IP DNS（198.18.0.0/15）下公网站点 discovery 按设计被
  SSRF 边界拦截（实测 400 unsafe_feed_url）——与 0013 Gate 5 同一
  已知环境限制，成功路径由 28 个离线测试覆盖；
- 浏览器侧 0010a RSSHub 实例清单（16 内置）不参与 0014 构造/预览
  （服务端 RSSHUB_BASE_URL 为唯一事实），设置页文案已诚实化；
- RSSHub 状态页（实例健康/路由可用性）→ 0018 Production。

### Key decisions（实现中锁定）

1. `RSSHUB_BASE_URL` + `RSSHUB_FRESHRSS_BASE_URL`（0008 双视角），
   feedUrl 用 FreshRSS 视角构造——订阅后由 FreshRSS 抓取；
2. RSSHub 预览 fetch：operator 配置固定 origin，重定向逐跳 origin
   校验，不适用 public-IP SSRF 校验（实例可为内网地址）；用户输入
   只到 path segment（regex + 编码 + 结构校验，注入不可能）；
3. discovery 服务不持有 FreshRSS 引用（read-only by construction）；
4. AddSourceDialog 单表面三模式；PreviewStage 共享订阅阶段；
5. 声明候选不预取（preview 阶段验证）；探测 bounded 5 端点首中即停。

### Verification（Final Gate，全部通过）

```text
BFF:    uv run pytest — 367 passed（305 存量 + 28 discovery + 34 rsshub）
Web:    vitest run — 466 passed / 35 files（440 存量 + 26 新增）
lint:   oxlint — 3 warnings（存量：Popover/Sidebar/FilterRulesPage）0 errors
build:  tsc -b 通过 + vite build 通过（chunk-size 提示为存量）
Live smoke（真实 RSSHub + 真实 FreshRSS 1.29.1，当前代码 BFF）:
        routes catalog configured=true + 14 路由
        preview hackernews / github-starred-repos(DIYgod) → 200 真实 metadata
        缺参/路径注入/未知路由 → 稳定 400/404
        订阅 E2E：subscribe 201 → 列表可见 → unsubscribe 204 → 基线还原
        vite 代理路径 /api/v1/rsshub/routes 浏览器可见面 200
```

### Git

```text
75efee6 docs: activate milestone 0014 source discovery
4f57144 feat: add source discovery contract and website feed discovery
b0927f4 feat: add RSSHub source configuration
1954e90 feat: connect source discovery to subscriptions and add source discovery UI
db8be2e docs: record milestone 0014 gate progress
dcfe8dd fix: harden source discovery integration (busy close guard + tab reset)
```

未 push、未 merge、未创建 PR；0015 未触碰。
