# 0014 — Source Discovery & RSSHub Integration

> Status: **In Progress** · Branch: `feat/0014-source-discovery-rsshub`
> Created by Gate 0 (2026-09-01) from baseline `26faaed` (main, 0013 merged).

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

（逐 Gate 追加）

## Completion notes

（Final Gate 追加）
