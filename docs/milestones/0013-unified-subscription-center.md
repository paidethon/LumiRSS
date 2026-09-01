# 0013 — Unified Subscription Center

> Status: **Completed** · Branch: `feat/0013-unified-subscription-center`
> Created by Gate 0 (2026-08-31) from baseline `ca2881a` (main, 0012 merged).
> Completed by Gate 5 (2026-09-01).

## Goal

用户可以完全在 Lumi 内完成普通 RSS/Atom 的：

```text
添加（preview → subscribe）
预览
分类（move / rename / create）
取消订阅（destructive confirmation）
OPML 导入 / 导出
```

而不需要打开 FreshRSS UI。

## Architecture invariants（全 milestone 生效）

```text
Native RSS / Atom → FreshRSS → FreshRSSAdapter / FreshRSSControlAdapter
                              → FastAPI BFF → React Web
```

- FreshRSS 是 RSS domain 唯一 source of truth；Lumi 不建第二套
  subscriptions/feeds/categories DB；
- 浏览器只访问 `/api/v1/*`；FreshRSS credential / auth token / action token
  永不进入浏览器；
- TanStack Query 拥有订阅 server state；Zustand 只拥有 UI/navigation state；
- 现有阅读路径（`GET /api/v1/feeds`、entries、entryRef/cursor）保持兼容，
  不为 0013 删除或破坏；
- Feed identity：management contract 使用 Lumi-owned opaque
  `subscriptionRef`（原则同 entryRef/cursor：opaque、validated、malformed →
  稳定 400），React 不自行拼装或理解 FreshRSS `feed/NN` id；
- Category contract：沿用既有 `category.id`（`user/-/label/<名>` 稳定 key）
  + `category.label`（展示名）；单分类模型（一个 Feed → 一个 Category），
  禁止多分类；默认分类身份不得依赖 UI 本地化字符串判断；
- Mutation safety：subscribe/unsubscribe/rename/move 超时后禁止无脑重试，
  优先 re-read server state → reconcile；
- Mutation 后优先 server-confirmed success → TanStack invalidate（不做
  optimistic updates / 不建第二套 Zustand subscription cache）。

## Gate 分解（每个 Gate 一个独立 New Chat，完成即 STOP 等人工确认）

```text
Gate 0 — 基线审计 + 0013 Spec（已完成，本文件）
Gate 1 — FreshRSS Control Plane（ControlAdapter + subscription/category API）
Gate 2 — 直接 RSS/Atom 预览 + 添加订阅（BFF safe-fetch + Web UI）
Gate 3 — Subscription Center + 真实分类 + 取消订阅（已完成）
Gate 4 — OPML 导入/导出 + 错误/健康状态 + escape hatch（已完成）
Gate 5 — 全量验收 + 文档收口（已完成）
```

## Blocking scope

```text
direct RSS/Atom URL 输入
preview before subscribe（preview 无副作用）
subscribe
unsubscribe（destructive confirmation）
real category management（move / rename / create）
OPML import/export（import 默认 merge，preview 先行）
health/error states（只展示有真实依据的状态）
FreshRSS advanced escape hatch（仅有安全 public URL 时）
```

## Non-goals（0013 明确禁止实现）

```text
website → RSS discovery（HTML rel=alternate / 常见路径猜测）
RSSHub route discovery / catalog / 参数表单（属 0014）
generic scraper / browser automation
AI / global search
category delete
多分类 feed 模型
feed title rename（除非 Gate 0 后人工批准）
拖拽持久化排序
```

## Decisions（Gate 0）

### BFF filtering migration — **Deferred**

0010a 的显示层过滤规则现状（审计事实）：

- 数据结构：`apps/web/src/store/app-settings.ts` 的
  `settings.filterRules: FilterRule[]`（Zustand + localStorage
  `lumirss-settings`，无服务端持久化）；
- 显示过滤实现：`apps/web/src/components/EntryList.tsx`（仅标题匹配全局
  启用规则，渲染时隐藏匹配项，不改动 FreshRSS 数据）；
- 设置 UI：`apps/web/src/components/settings/FilterRulesPage.tsx`（注释中
  预告 "BFF 读取层过滤将在 0013 提供；来源级规则从订阅管理侧入口添加"）。

Defer 理由：

1. 迁移需要服务端持久化 filter rules —— 当前 BFF 无任何服务端设置存储
   （0017 才规划 server-side settings）；
2. BFF 层过滤与现有 cursor pagination 冲突：FreshRSS 上游过滤 + n=20
   分页边界由 continuation 决定，BFF post-filter 会打破每页数量/下一页
   语义，需要 over-fetch 或重分页设计；
3. 会同时修改 entries API 契约与 Settings 架构，明显扩大 0013 范围。

结论：显示层过滤保持现状（诚实文案已有），BFF 过滤迁移留待后续
milestone（候选 0017 统一设置）。是否改判由人工在 Gate 0 确认后生效；
除非人工明确改判为 Included，Gate 4 不得顺手实现。

## 基线审计事实（供后续 Gate 直接引用）

### BFF 已有能力（services/bff/src/lumirss/）

- `GET /api/v1/feeds`：返回真实 `category { id, label }`（无分类 → null）；
- `GET /api/v1/entries`：`view` / `feedUrl` / `sourceType`（仅 "rss"）/
  `categoryId`（greader label stream，服务端过滤）+ opaque cursor；
- `FreshRSSAdapter`：`_auth_token` / `_action_token` 缓存、
  `_get_action_token()`、subscription/list 解析（含真实 category）、
  默认分类本地化名 fallback（"未分类" → "Uncategorized" 重试）、
  FreshRSS 1.29.1 已验证行为（read/edit-tag/token/stream）；
- `set_entry_state`：set 语义写路径（auth 失效清 token 重登一次重试）；
- entryRef：`e1.` + base64url（opaque 模式参考）。

### Web 已有能力（apps/web/src/）

- `api/client.ts` / `queries.ts` / `types.ts`：Feed（含 category）/
  entries / detail / state mutation；query key `['feeds']` 全局共享；
- `Sidebar.tsx`：`mergeFeedsByCategory` 真实分类树（category.id 合并，
  未分组排最后）；scope 模型 `ContentScope`（all/rss/rss-feed/rss-category，
  `lib/navigation.ts`）；
- `SubscriptionsPage.tsx`：真实只读列表 + 本地搜索；「添加 RSS / OPML 导入 /
  分组管理」禁用 + 0013 徽标；**存在 0011 遗留假设**：「Feed 契约无分类
  字段 → 单一未分组折叠组」——与当前 BFF 契约不一致，Gate 3 需改为真实
  category grouping；
- `store/reader-ui.ts`：section（home/subscriptions/search/favorites）+
  scope + view，无 persist。

### FreshRSS Control Plane 待验证（Gate 1 对 1.29.1 实测）

```text
subscription/edit（subscribe/unsubscribe/move/rename）
subscription/quickadd（如使用）
category add / rename
tag/list（如需要）
```

以本地开发环境实测为准，官方 GReader 文档仅作参考。

## Gate Progress

### Gate 0

Status: Completed (2026-08-31)

Implemented:

- 基线审计：branch `main` @ `ca2881a`，working tree clean，0012 已合并；
- 创建分支 `feat/0013-unified-subscription-center`；
- 创建本 milestone 文档（Goal / scope / non-goals / decisions / 审计事实）；
- `docs/README.md`：0012 → Completed（已是）、0013 → Active；
- `docs/ROADMAP.md`：0013 条目链接 milestone 文档。

Decisions:

- BFF filtering migration：**Deferred**（理由见上）；
- Feed title rename：默认 defer（除非人工批准）；
- subscriptionRef：Lumi-owned opaque（Gate 1 设计具体格式）。

Tests: 无代码改动，未运行测试（文档-only Gate）。

Known gaps:

- ROADMAP 中旧的 "0013 activates BFF-layer filtering" 依赖描述与
  PROJECT_STATE/devlog 引用在文档清理时已移除，现存引用仅存在于历史
  milestone 归档与 web 代码注释中（保持不动）。

Next Gate: Gate 1 — FreshRSS Control Plane（FreshRSSControlAdapter 复用
现有 auth/action-token，新增 subscription/category mutation API）。

### Gate 1

Status: Completed (2026-08-31)

Implemented:

- `FreshRSSSession`（freshrss.py 内抽取）：credential / auth token /
  action token / 共享 HTTP transport 的唯一持有者；
  `FreshRSSAdapter`（读路径）改为继承它，行为不变；
- `FreshRSSControlAdapter`（adapters/freshrss_control.py）：borrow 同一
  session 实例，绝不复制登录/token 状态（测试断言单次 ClientLogin）；
  - `list_subscriptions` / `list_categories`（tag/list folders，含空分类）；
  - `subscribe`（server-confirmed：写入后 re-read 回读新订阅）；
  - `unsubscribe` / `move_category`（写入前存在性预检，恰好一次写入）；
  - `rename_category`（no-op probe 判定默认分类 + 写后 post-check
    捕获上游静默 no-op）；
- `subscriptionref.py`：Lumi-owned opaque `subscriptionRef`（`s1.` +
  base64url(`feed/<N>`)，仅接受 well-formed feed id，malformed → 400）；
- BFF API（main.py）：
  - `GET /api/v1/subscriptions`（含 subscriptionRef/title/feedUrl/category）；
  - `GET /api/v1/categories`（id/label，同 feeds 分类契约）；
  - `POST /api/v1/subscriptions`（201；409 已订阅 / 400 invalid_feed_url
    / 400 feed_rejected）；
  - `PATCH /api/v1/subscriptions/{subscriptionRef}`（204 move；categoryId
    必须已存在，否则 404）；
  - `DELETE /api/v1/subscriptions/{subscriptionRef}`（204）；
  - `PATCH /api/v1/categories/{categoryId}`（204 rename；409
    category_label_conflict / default_category_immutable）；
  - 新增 10 类稳定错误映射（400/404/409/502/503 + error.type）；
  - `GET /api/v1/feeds` 等既有读路径零改动。

FreshRSS 1.29.1 verified behaviors（源码 + 本地实例实测，2026-08-31）：

- `subscription/edit` 完全不校验 `T` action token（空/缺失也 200），
  仍按协议发送；成功 = 200 + body "OK"；
- subscribe：重复订阅 / 无法添加 → 400 "Bad Request!"；
  `a=user/-/label/<名>` 目标分类不存在时会自动创建（Lumi 侧选择
  预检拦截，不利用自动创建——建分类 UX 留给 Gate 3 决策）；
- unsubscribe：未知 feed id → 400；`feed/<数字id>` 或 `feed/<url>` 均可；
- move（ac=edit + a）：同上自动创建语义；未知 feed → 400；
- `rename-tag` 会校验 `T`（garbage → 401 + `Google-Bad-Token: true`）；
  - 默认分类不可 rename：DAO 强制其展示名始终为本地化名
    （zh-cn "未分类"），API 可见名 ≠ DB 真名 "Uncategorized"，
    `searchByName` 永远失配 → 400（实测确认）；
  - rename 到碰撞名可返回 "OK" 但 SQL UPDATE 被 UNIQUE(name)/同名
    tag 静默阻断（实测复现）——必须写后回读验证；
  - 实测陷阱：把非默认分类 rename 为本地化默认名（如 "未分类"）会
    创建出与默认分类显示重名的真分类（本实例已复现并清理）；
    Lumi 侧以 `label == "Uncategorized"`（上游 DB 常量，非本地化串）
    保留字 + 全量重名预检拦截；
- `tag/list`：`type: "folder"` = 分类（含空分类），`type: "tag"` =
  用户标签，其余为 state 伪 tag；是唯一能列出空分类的端点；
- 默认分类身份判定不依赖 UI 本地化字符串：本实例默认分类 DB 真名
  为 "Uncategorized"（id=1），greader 层展示为本地化名。

Decisions（Gate 1）：

- subscriptionRef 格式：`s1.` + base64url(`feed/<N>`)；decode 只接受
  well-formed `feed/<正整数>`；
- move/subscribe 的 categoryId 必须已存在（404）：不利用 FreshRSS
  自动建分类语义，避免拼写错误静默建分类；create-category 入口
  由 Gate 3 决策（可直接复用 subscription/edit 的自动创建）；
- rename 默认分类 → 稳定 409 `default_category_immutable`（提示
  用户该分类由 FreshRSS 管理）；
- Mutation safety：所有 mutation 恰好执行一次；401 重登重试安全
  （FreshRSS 先鉴权后变更）；timeout/连接错误绝不重试，交由调用方
  re-read + reconcile；
- 命名冲突预检（订阅 URL / 分类 label）在写入前完成，避免依赖
  上游 400 的语义模糊。

Tests:

- 新增 `test_subscriptionref.py`（16 cases）、`test_freshrss_control.py`
  （35 cases：协议 form 体断言、错误映射、共享 session 单次
  ClientLogin、401 一次性重登、默认分类 immutability、silent no-op
  post-check）、`test_subscriptions_route.py`（17 cases：route 契约、
  malformed ref 400、409/404 映射、读路径共存）；
- 全量 BFF tests：197 passed；
- 真实 smoke（本地 FreshRSS 1.29.1，端到端）：subscribe 201 → move
  204 → rename 204 → rename 默认分类 409 → rename 碰撞名 409 →
  unsubscribe 204，临时数据已全部清理还原。

Known gaps:

- 无 create-category Lumi API（Gate 3 决策，见 Decisions）；
- feed title rename 未实现（Gate 0 决定 defer）；
- `subscription/quickadd` 未采用（subscription/edit 已覆盖且错误
  语义更可控）；
- Web 侧（queries/types/UI）属 Gate 2/3，本 Gate 未触碰 apps/web。

Next Gate: Gate 2 — 直接 RSS/Atom 预览 + 添加订阅（BFF safe-fetch +
Web UI；将复用本 Gate 的 subscribe mutation 与 subscriptionRef）。

### Gate 2

Status: Completed (2026-08-31)

Implemented:

- BFF `feed_preview.py`：可复用的 safe-fetch boundary + 离线 feedparser
  解析（`safe fetch → bounded bytes → parse RSS/Atom`，parser 绝不自己联网）：
  - URL 结构校验：http/https only、拒绝嵌入式 credentials、长度/端口限制；
  - DNS 解析后逐 IP 校验（IPv4 + IPv6，含 IPv4-mapped IPv6 与 NAT64
    前缀展开）：拒绝 localhost/private/link-local/reserved/multicast/
    unspecified/CGNAT/metadata（169.254.169.254）；
  - timeout（复用共享 client 的 10s/5s connect）；
  - bounded response（2 MiB：Content-Length 快路径 + 流式读取上限）；
  - bounded redirects（≤5 跳，手动循环，每一跳重新过全部 URL/DNS/IP
    校验，redirect-to-private 被拦截；无 follow_redirects=True）；
  - 解析只取可靠字段：title/siteUrl（仅绝对 http(s)，否则 null）/
  description（HTML 转纯文本，限长）/format（rss|atom，由 feedparser
    version 前缀判定，RDF 归入 rss）；不抓正文、不抓条目。
- BFF `POST /api/v1/feed-preview`（无副作用）：读取订阅列表计算
  `alreadySubscribed`，从不触碰任何 mutation；新增 4 类稳定错误映射
  （400 unsafe_feed_url / 502 feed_fetch_error / 413 feed_too_large /
  400 not_a_feed，另复用 400 invalid_feed_url）；service 懒创建缓存于
  app.state（与既有 adapter 模式一致）。
- Web：`AddSubscriptionDialog`（复用 Dialog primitive，
  fullscreenOnMobile——桌面 Modal / 移动全屏同一实现，无第二套 modal
  framework）：
  - 闭环：输入直接 RSS/Atom URL → 预览 → 真实 metadata 卡片 → 真实分类
    （`GET /api/v1/categories`，含空分类，「默认分类（不指定）」选项）
    → 确认 → `POST /api/v1/subscriptions`（Gate 1）→ 成功提示；
  - 状态齐全：loading（Skeleton）、invalid feed / timeout / unsafe URL /
    duplicate（alreadySubscribed 提示 + 订阅 409 → 同文案）/ success /
    error；分类加载失败时降级为默认分类并可重试；
  - 普通网页 URL：前端本地拦截 + BFF not_a_feed 双重诚实提示（
    「当前请填写直接 RSS / Atom 地址；网站来源发现属于后续 Source
    Discovery」，不做 rel=alternate 发现 / 不猜 /feed）；
  - a11y：Escape 关闭、焦点 trap/还焦（Dialog primitive 内建）、label
    关联、≥44px 输入/选择、isPending 双击防重（预览与订阅均禁用）、
    提交中不允许遮罩/取消误关；
  - mutation 后仅 invalidate（feeds/categories/entries），不做
    optimistic updates，不建第二套 Zustand subscription cache。
- Web `SubscriptionsPage`：「添加 RSS」从 disabled 占位换为真实入口
  （aria-haspopup=dialog）；OPML 导入 / 分组管理仍禁用 + 0013 徽标（Gate
  3/4）；`lib/direct-feed-url.ts` 前端第一道结构校验（SSRF 等安全校验
  只在 BFF，不重复实现）。
- 新增 BFF 依赖：`feedparser 6.0.14`（BSD-2-Clause；纯解析、久经维护、
  httpx 之外的唯一新增；只以 bytes 输入离线使用）+ 传递依赖
  `feedparser-sgmllib 2.1.0`（MIT）。

Decisions（Gate 2）：

- preview 用 mutation hook（pending/error 语义 + 双击防重）但不
  invalidate 任何 query——预览是读操作，结果存组件本地 state；
- `alreadySubscribed` 是读取时快照，最终一致性由 subscribe 侧服务端
  409 预检兑底（Gate 1 已有）；
- DNS/IP 校验基于 getaddrinfo 全部结果逐个检查；已知理论 TOCTOU
  （校验后连接前的 DNS rebinding）风险接受（httpx 连接层无 hook，
  自建 transport 超出本 Gate 范围）；
- description 用 BFF 既有 `html_to_text` 归一化（不可信输入，只输出
  纯文本）。

Tests:

- 新增 `test_feed_preview.py`（61 cases）：URL 校验、IP 边界（含
  IPv4-mapped/NAT64/CGNAT/metadata）、离线解析（RSS/Atom/RDF/HTML
  误用/无标题/javascript link）、重定向逐跳重验证、redirect-to-private/
  localhost 拦截、循环上限、非 http 跳转目标、超大响应（快路径 + 流式）、
  连接超时、DNS 失败、路由错误映射 + **无副作用证明**（service 级：
  preview 后 control 只被读列表；route 级：POST preview 前后
  `/api/v1/subscriptions` 完全一致）；
- 新增 `add-subscription.test.tsx`（14 cases）：预览 metadata 展示、
  普通网页本地拦截（不发预览请求）、not_a_feed 诚实提示、timeout
  重试、unsafe URL、订阅成功闭环（含分类传参）、alreadySubscribed
  禁用、409 冲突文案、订阅后 invalidate → 新 feed 出现在订阅页、
  Escape + 还焦、空 URL 禁用、双击防重；direct-feed-url 纯函数；
- 更新 `gate4-pages.test.tsx`：添加 RSS 真实入口断言；
- 全量 BFF tests：258 passed；Web 全量：413/414 passed（1 个存量
  失败 `gate3-pages` FavoritesPage「最近收藏」分组，git stash 验证
  与本次改动无关）；oxlint 3 warnings（存量）0 errors；tsc -b 通过。

Known gaps / risks:

- DNS rebinding TOCTOU：校验与实际拨号之间理论可变（见 Decisions）；
- 移动端全屏 Dialog 未做真实浏览器截图验证（仅契约测试）；
- gate3-pages 存量 flaky（FavoritesPage 分组）未修（超出本 Gate 范围，
  建议后续 Gate 顺手修复）；
- feedparser 宽容解析：畸形但带 version 的文档可能通过；风险低
  （预览只展示元数据，不执行内容）。

Next Gate: Gate 3 — Subscription Center + 真实分类 + 取消订阅
（订阅页真实 category grouping、move/unsubscribe UI、create-category
决策）。

### Gate 3

Status: Completed (2026-08-31)

Implemented:

- BFF `freshrss_control.py`：新增 `move_to_new_category(stream_id,
  label)`——新建分类并把订阅移入。写入前 label 规范化校验（复用
  `_validated_label`，从 rename_category 提取共享）+ 保留字
  （Uncategorized）/重名预检（→ 409 `category_label_conflict`），
  写入后回读 post-check（FreshRSS 假成功 → 502）；
- BFF `main.py`：`SubscriptionPatch` body 扩展为 `categoryId |
  newCategoryLabel` 二选一（model_validator，违反 → 422），
  `PATCH /api/v1/subscriptions/{ref}` 分支调用 move 已有/新建分类；
  DELETE（unsubscribe）为 Gate 1 已有能力，本 Gate 只做 Web 侧接线；
- Web API：`getSubscriptions` / `moveSubscription`（PATCH，二选一
  body）/ `unsubscribeFeed`（DELETE）/ `renameCategory`（PUT）；
- Web hooks：`useSubscriptions` + 三个 mutation hook，共享
  `invalidateSubscriptionState`（统一失效 feeds/categories/
  subscriptions/entries）；`useSubscribeMutation` 一并改用同一
  helper（订阅页数据源已从 `['feeds']` 切到 `['subscriptions']`）；
- Web UI（三个新对话框，均复用 Dialog primitive，fullscreenOnMobile）：
  - `MoveSubscriptionDialog`：目标分类下拉（已有分类 + 「＋ 新建分类…」
    特殊值切换为输入框；新建时说明将创建分类并移入）；
  - `UnsubscribeDialog`：两阶段双重确认（confirm → final danger），
    明确显示 Feed 名 + URL + 破坏性警告；文案不承诺「历史文章保留」
    （FreshRSS 侧行为未验证，只说可在 Lumi 重新添加）；
  - `RenameCategoryDialog`：预填当前名，未修改时保存禁用；
  - 新增 `lib/management-errors.ts`：稳定错误 type → 中文文案；
- Web `SubscriptionsPage` 重写：数据源 `useSubscriptions`，
  `groupByCategory` 真实分组（category 缺失 → 「未分组」排最后；
  其余按 label 稳定排序，无任何硬编码分类名）；Feed 行 icon/title/
  域名/⋯ 菜单；分类行 disclosure（带 `aria-label={label，N 个订阅源}`）
  + ⋯ 菜单（仅重命名，无删除）；本地搜索过滤；OPML 禁用 + 0013 徽标；
  scope reconciliation useEffect：订阅列表中 feedUrl 消失 → 回退
  ALL_SCOPE；categories 中 categoryId 消失 → 回退 ALL_SCOPE。

Decisions（Gate 3）：

- create-category 不新增独立 `POST /categories` 端点：FreshRSS
  greader 协议唯一可靠的分类创建通道是 `subscription/edit` 的
  自动创建语义（`a=user/-/label/<名>`），故「新建分类」= 把一个 feed
  移入不存在的分类（PATCH `{newCategoryLabel}`）。写前预检防拼写
  错误静默建分类、防用本地化默认名（「未分类」）铸造重名真分类
  （保留字 Uncategorized 在 DB 层拦截）；写后 post-check 回读；
- 无 optimistic updates：unsubscribe/rename/move 一律
  server-confirmed → `invalidateSubscriptionState`（覆盖 Sidebar
  RSS tree + 订阅页 + entries），不建第二套本地分类状态；
- Feed title rename：defer——Roadmap blocking 是 rename/move
  category；FreshRSS 1.29.1 rename feed 未验证、Gate 0 milestone
  未列入，不扩大范围；
- 空分类（tag/list 可见）不出现在订阅页（分组由 subscriptions
  派生），但会出现在移动对话框下拉（tag/list 含空分类）——接受，
  与 AddSubscriptionDialog 分类下拉一致。

Tests:

- 新增 `subscription-management.test.tsx`（16 cases）：真实分组/未分组
  排序、本地搜索、移动 PATCH body、新建分类 PATCH body、409 冲突文案、
  unsubscribe 双重确认 + DELETE + 列表失效、deleted feed scope 回退、
  rename PUT、默认分类 rename 409、OPML 徽标、loading/empty/error；
- 更新 `gate4-pages.test.tsx`（改订阅页 `/api/v1/subscriptions` 契约 +
  真实分组断言）与 `add-subscription.test.tsx`（invalidate 闭环改
  subscriptions 数据源）；
- BFF：`test_freshrss_control.py` 新增 move_to_new_category 用例
  （含重名/保留字预检、假成功 post-check、不存在订阅），
  `test_subscriptions_route.py` 新增 route 分支与 422 二选一用例；
- 运行：BFF 目标测试 59 passed，全量 270 passed；Web 目标 47 passed，
  全量 429/430（1 个存量 flaky `gate3-pages` FavoritesPage 分组，
  git stash 验证与本 Gate 无关）；oxlint 3 warnings（存量）
  0 errors；`tsc -b` 通过；`vite build` 通过；
- Live smoke（真实 FreshRSS 1.29.1，当前代码 BFF）：move-to-new 204
  且分类创建 + feed 归属可见；rename 204；默认分类 rename → 409
  `default_category_immutable`；冲突名 → 409 `category_label_conflict`；
  UI 实操：移动后订阅页 + Sidebar RSS tree 同步刷新（invalidate 生效）；
  smoke 数据已还原（feed 移回未分类，临时分类清理）。

Known gaps / risks:

- 桌面（≥1024）无订阅管理入口：订阅页是 0011 的移动端一级页面
  （`lg:hidden`），本 Gate 未扩大到桌面 shell——后续 Gate 顺手补；
- 真实浏览器验证补充了 Gate 2 遗留项：390/430/768 订阅页 +
  dark mode + Escape 关闭/还焦均实测通过（1024+ 桌面 shell 无该页）；
- gate3-pages 存量 flaky（FavoritesPage 分组）未修（超出本 Gate
  范围）；
- FreshRSS unsubscribe 后历史文章是否保留未验证（UI 文案已按
  不承诺处理）。

Next Gate: Gate 4 — OPML 导入/导出 + 错误/健康状态 + escape hatch
（复用本 Gate 的 categories/subscriptions 读取层与
invalidateSubscriptionState）。

### Gate 4

Status: Completed (2026-09-01)

Implemented:

- BFF 新增 `opml.py`：`parse_opml`（defusedxml 解析；上限 2 MiB /
  深度 ≤ 8 / feed 数 ≤ 500；xmlUrl 过 `_validate_feed_url`（http/https、
  ≤ 2048）；文件内重复 URL 保留首个并如实上报 `file_duplicates`）+
  `OpmlService.preview`（只读，无任何写入）/ `import_opml`（merge）；
- BFF `main.py` 四条新路由：`GET /api/v1/opml/export`（代理 FreshRSS
  `subscription/export`，attachment `text/x-opml`）、
  `POST /api/v1/opml/import/preview`（无副作用）、
  `POST /api/v1/opml/import`（merge 写入）、`GET /api/v1/freshrss-ui`
  （escape hatch 元信息）。上传为流式 bounded read（超 2 MiB → 413
  `opml_too_large`）；错误映射新增 `opml_invalid`(400) /
  `opml_too_large`(413) / `opml_too_many_feeds`(400)；
- BFF `freshrss_control.py`：`export_opml`（10 MiB 上限 + OPML root
  sanity check）；`freshrss.py` 新增 `_authorized_get_raw`；
- BFF `config.py`：可选 `FRESHRSS_PUBLIC_URL`（校验：绝对 http(s)、
  无 credentials/query/fragment）；`freshrss-ui` 端点返回 `{url|null}`，
  配置非法 → `null`（不出假链接也不 crash）；
- Web API 层：`exportOpml`（blob 下载，浏览器不接触 FreshRSS 凭据）/
  `previewOpmlImport` / `importOpml` / `getFreshRssUiUrl` + 三个 hook
  （import 后 `invalidateSubscriptionState` 重新拉取）；
- Web `lib/opml-import.ts`：`useOpmlImportFlow` 状态机（file →
  preview → confirm → result）+ `opmlFailureLabel` 稳定失败码文案 +
  前端第一道 2 MiB 拦截；`components/OpmlImportFlow.tsx` 为共享摘要
  卡片（Preview/Result/Error，只渲染 server-confirmed 数据）；
- Web 两个外壳复用同一流程：订阅页 `OpmlImportDialog`（移动端）与
  设置 → 订阅与来源 的内联 `SourcesSettingsSection`（全断点可用，
  顺带补上 Gate 3 已知缺口：桌面无订阅管理入口）；`SubscriptionsPage`
  「导入 OPML」改为真实按钮；
- 错误状态产品化：`management-errors.ts` 扩展
  connection_error / authentication_error / configuration_error /
  upstream_error / opml_invalid / opml_too_large / opml_too_many_feeds /
  feed_rejected；FreshRSS 状态块只报告真实请求结果（错误 type 文案
  或「连接正常，当前 N 个订阅源」），无任何伪健康指标；
- escape hatch：仅当 `/api/v1/freshrss-ui` 返回非 null URL 才渲染
  「高级：在 FreshRSS 中管理」外链（target=_blank
  rel=noopener noreferrer）；未配置 → 诚实说明，不渲染链接。

Decisions（Gate 4）：

- **新增依赖 defusedxml 0.7.1**（license：PSF-2.0；来源 PyPI；理由：
  OPML 是 untrusted XML，stdlib ElementTree 不防 DTD entity expansion
  / 外部实体，defusedxml 在解析层拒绝危险 entity 行为）。经 `uv add`
  安装并写入 `uv.lock`；
- OPML 导出直接代理 FreshRSS 原生 `subscription/export`（实测 1.29.1
  返回标准 OPML 2.0 嵌套 outline），不在 BFF 重新合成——协议原生
  内容即「只有订阅 + 分类」，天然排除 API keys / settings dump /
  read history / favorites；
- OPML 导入 merge 语义：每个新 feed 先 `subscribe`（落默认分类），
  有非保留字 label 再 move（复用 Gate 3 `move_to_new_category`
  自动创建，含预检 + post-check）；分类 move 失败不回滚订阅
  （`categoryApplied=false` 如实上报）；单 feed 失败收集到 `failed`
  （稳定 code），不中断整体；绝不删除/覆盖现有订阅
  （destructive restore 明确不做）；
- 默认分类保留字：OPML 中 label 为 Uncategorized 的条目视为默认
  分类，跳过 move（避免用 DB 保留字铸造真分类）；
- escape hatch URL 绝不从 `FRESHRSS_BASE_URL` 推导（那可能是 Docker
  内部主机名如 `http://freshrss:80`），必须显式配置
  `FRESHRSS_PUBLIC_URL`（已写入 `.env.example` 说明）；
- BFF filtering migration：Gate 0 判定 Deferred 维持不变，本 Gate
  未实现。

Tests:

- BFF 新增 `test_opml.py` 35 cases：parse 纯函数（分类提取/无效
  URL/畸形 XML/DTD billion-laughs 拒绝/去重/超深/超量/超大）、
  preview 无副作用证明、merge 导入（added/duplicates/failed/
  categoriesCreated/文件内重复上报）、分类复用 vs 创建 vs 保留字 vs
  move 失败容忍、export MockTransport（attachment header/非 200 →
  502/超大 → 502）、路由级（413/400/502/freshrss-ui 三态）；
- BFF 全量 **305 passed**（270 存量 + 35 新增）；
- Live smoke（真实 FreshRSS 1.29.1）：export 1168 bytes 有效 OPML →
  preview（4 feeds, 0 new, 4 dups）→ import 自身导出 = 零副作用
  （added 0 / failed 0，无任何 mutation）；
- Web 新增 `opml-import.test.tsx` 10 cases：严格 preview-before-
  mutation（预览前无 import 请求）、确认后 server-confirmed 结果 +
  invalidate 重拉、2 MiB 本地拦截零请求、opml_invalid 文案 + 确认
  禁用、全部重复确认禁用、导出下载（createObjectURL/click）、导出
  失败文案、FreshRSS 状态真实结果、authentication_error 文案 +
  无伪指标断言、escape hatch 有 URL 渲染 noopener 外链；
- 更新存量测试：`subscription-management` / `gate4-pages`（OPML
  从禁用徽标改为真实入口断言）、`gate-b`（sources 页从 3 个
  planned 改为 OPML 真实控件 + RSSHub planned）、`gate3-pages`
  （修复固定日期随时间过期导致的假失败：改为动态「今天」+ 远期
  固定日期）；
- Web 全量 **440 passed**（33 files）；oxlint 3 warnings（存量）
  0 errors；`tsc -b` 通过；`vite build` 通过。

Known gaps / limitations:

- escape hatch 需要服务端显式配置 `FRESHRSS_PUBLIC_URL` 才出现；
  当前 dev 环境未配置（`freshrss-ui` 返回 null），设置中心显示
  诚实说明文案。若部署环境浏览器可达 FreshRSS（如
  `http://127.0.0.1:8080` 或反代域名），配置后入口即出现；
- OPML 导入对「分类 move 失败」采取容忍策略（订阅已添加、留在
  默认分类，`categoryApplied=false` 如实上报），不自动重试；
- 上限：导入文件 2 MiB / 500 feeds / 深度 8（前端 + BFF 双层）；
  导出 body 10 MiB。均为 bounded 输入约定；
- 预览的「重复」判定仅基于订阅地址精确匹配（如实文案已说明），
  不做标题模糊匹配。

Next Gate: Gate 5 — 全量验收 + 文档收口。

### Gate 5

Status: Completed (2026-09-01)

Implemented:

- Step 5.1 Scope audit：正式 Acceptance 逐项核对（见下方
  Implementation Results — Implemented/Deferred/Not implemented 清单）；
- Step 5.2 Architecture audit：FreshRSS 唯一 source of truth（无 Lumi
  RSS shadow DB，BFF 源码 grep sqlite/shadow 零命中）；浏览器仅访问
  `/api/v1`（`client.ts` `API_BASE = '/api/v1'` 相对路径，无任何
  VITE_ 凭据环境变量）；`FreshRSSControlAdapter` 方法面窄
  （list/subscribe/unsubscribe/move/rename/export_opml 共 8 个公开方法，
  借用共享 `FreshRSSSession`，无第二套 auth/action-token 系统）；
  TanStack Query 拥有全部订阅 server state（store/ 仅 4 个 UI
  Zustand store：app-settings / read-later / reader-ui / theme）；
- Step 5.3 0014 boundary audit：BFF 源码 RSSHub 零命中；Web 无
  rel=alternate 发现 / 常见路径猜测 / RSSHub catalog / route matching
  （AddSubscriptionDialog 注释明确诚实提示「网站来源发现属于后续
  Source Discovery」，不做发现、不猜路径、不抓网页）；
- Step 5.4 全量回归（见 Verification）；
- Step 5.5 disposable FreshRSS 集成 smoke：预览→订阅→建分类→重命名
  →OPML 导出→OPML 导入预览+导入→取消订阅全链路（见 Verification，
  数据已全部还原）；
- Step 5.6 视觉/响应式：390/430/768（移动 shell 订阅页）+
  1024/1280/1440（桌面 Settings→订阅与来源）+ dark + Escape/焦点 +
  两阶段取消订阅 + 空状态，console 零 error；
- Step 5.7 文档收口（本节 + Implementation Results + README/ROADMAP/
  architecture README 状态同步）；
- 环境事实：本地 dev BFF 进程此前为 Gate 4 之前的旧代码（缺全部
  0013 路由），Gate 5 重启为当前代码后完成全部验证。

Known gaps / notes:

- 宿主机 DNS 为 TUN 代理 fake-IP 模式（所有外部域名解析为
  198.18.0.0/15 保留网段），`feed-preview` 的 SSRF IP 校验按设计
  全部拦截——preview 成功路径的 live 验证在该环境不可行（非代码
  缺陷；成功路径由 61 个离线测试覆盖；订阅写入路径经 Docker 内
  FreshRSS 抓取，不受影响）；
- Web 全量首跑出现 1 个 `mobile-reader.test.tsx` timing flaky
  （单独运行 3/3 通过，全量重跑 440/440 全绿；0013 未触碰任何
  Reader 组件，判定与本 milestone 无关）。

## Implementation Results

> 收口于 Gate 5（2026-09-01）。

**Summary**: FreshRSS Control Plane（ControlAdapter + subscription/
category management API）+ 直接 RSS/Atom 预览与订阅（BFF safe-fetch
boundary）+ Subscription Center（真实分类 move/rename/create + 两阶段
取消订阅）+ OPML 导入/导出（preview 先行、merge 语义）+ 错误/健康
状态 + FreshRSS escape hatch。用户可在 Lumi 内完成普通 RSS/Atom 全部
订阅生命周期管理，无需打开 FreshRSS UI。

### Scope audit（Step 5.1 逐项）

Implemented:

- direct RSS/Atom URL 输入与添加（Gate 2）；
- preview before subscribe——无副作用（service + route 双重证明，
  Gate 2）；
- subscribe（server-confirmed：写入后 re-read，Gate 1/2）；
- real categories（`GET /api/v1/categories`，tag/list folders 含空分类）；
- category move（已有分类 + 新建分类二选一，Gate 3）；
- category rename（含默认分类 immutable 与重名预检，Gate 1/3）；
- category create（经 move-to-new 通道，无独立 POST /categories，Gate 3）；
- unsubscribe + 两阶段 destructive confirmation（Gate 3）；
- OPML import（merge，preview 先行）/ export（代理 FreshRSS 原生导出，
  Gate 4）；
- error states（稳定错误码 → 中文文案；FreshRSS 状态块只报告真实请求
  结果，无伪健康指标，Gate 4）；
- FreshRSS escape hatch（显式配置 `FRESHRSS_PUBLIC_URL` 才渲染外链，
  未配置 → 诚实说明，Gate 4）。

Deferred:

- BFF filtering migration（Gate 0 决策，候选 0017 统一设置）；
- feed title rename（Gate 0/3 决策：FreshRSS 1.29.1 行为未验证、
  非 blocking scope）；
- FreshRSS unsubscribe 后历史文章是否保留（UI 文案按不承诺处理）。

Not implemented（Non-goals，0014+ 范围）：

- website → RSS discovery（rel=alternate / 常见路径猜测）；
- RSSHub route discovery / catalog / 参数表单；
- generic scraper；
- category delete；多分类模型；拖拽持久化排序。

### Key decisions

1. `FreshRSSSession` 单一持有者：读路径 Adapter 与 ControlAdapter 共享
   同一 session（单次 ClientLogin、共享 HTTP transport），无第二套
   auth/action-token 系统；
2. subscriptionRef / category 契约：Lumi-owned opaque `s1.` +
   base64url(`feed/<N>`)（原则同 entryRef/cursor）；malformed → 稳定 400；
3. Mutation safety：所有 mutation 恰好一次（401 一次性重登安全；timeout/
   连接错误不重试）；写前预检 + 写后回读 post-check（捕获 FreshRSS
   静默 no-op / 假成功）；
4. 分类创建不新增端点：复用 `subscription/edit` 自动创建语义
   （move-to-new-category），预检防拼写错误与保留字（Uncategorized）；
5. Server-confirmed → invalidate：无 optimistic updates，无第二套
   Zustand subscription cache；
6. feed-preview 安全边界：safe fetch（URL/DNS/逐 IP 校验含 IPv4-mapped
   /NAT64/CGNAT/metadata、bounded 2 MiB、bounded redirects ≤5 跳逐跳重验
   证）→ 离线 feedparser（解析器不联网）；已知理论 DNS rebinding
   TOCTOU 接受（httpx 连接层无 hook）；
7. OPML：defusedxml 解析（拒绝 DTD entity 攻击）+ 双层 bounded（前端
   2 MiB + BFF 2 MiB/500 feeds/深度 8）；导入 merge 语义，绝不删除/
   覆盖现有订阅；导出直接代理 FreshRSS 原生 `subscription/export`
   （天然只含订阅 + 分类，无 API keys/settings/read history）；
8. escape hatch URL 绝不从 `FRESHRSS_BASE_URL` 推导，必须显式配置
   `FRESHRSS_PUBLIC_URL`（防 Docker 内部主机名泄漏进浏览器）。

### API

新增 BFF 端点（全部在 `/api/v1` 下，浏览器唯一入口）：

```text
GET    /subscriptions                      订阅管理视图（含 subscriptionRef）
GET    /categories                          分类列表（含空分类）
POST   /subscriptions                       订阅（201；409/400 错误映射）
PATCH  /subscriptions/{ref}                move（categoryId | newCategoryLabel 二选一）
DELETE /subscriptions/{ref}                取消订阅（204）
PATCH  /categories/{categoryId}            rename（409 conflict/immutable）
POST   /feed-preview                        预览（无副作用）
GET    /opml/export                         导出（attachment text/x-opml）
POST   /opml/import/preview                 导入预览（无副作用）
POST   /opml/import                         导入（merge）
GET    /freshrss-ui                         escape hatch 元信息（{url|null}）
```

既有读路径（`GET /feeds`、entries、entryRef/cursor）零破坏。

### Security

- 上游凭据 / auth token / action token 永不进入浏览器（本次审计
  代码级确认）；
- feed-preview SSRF 防护（见 Key decisions 6），redirect-to-private
  被拦截；
- OPML untrusted XML：defusedxml 拒绝 DTD entity expansion（billion
  laughs 测试覆盖）；
- 外链（escape hatch）：`target=_blank rel="noopener noreferrer"`；
- 无 secrets 进入 Git（`.env` 不入库；新增依赖 feedparser 6.0.14
  BSD-2-Clause + feedparser-sgmllib 2.1.0 MIT + defusedxml 0.7.1
  PSF-2.0，均已在 uv.lock 固定）。

### Verification

```text
BFF:    305 passed（全量，197 → 270 → 305 逐 Gate 递增）
Web:    440 passed / 33 files（全量重跑；首跑 439/440，1 个
        mobile-reader timing flaky，单独运行通过，与 0013 无关）
lint:   oxlint 3 warnings（存量）0 errors
build:  tsc -b + vite build 通过
Live smoke（disposable feed，真实 FreshRSS 1.29.1）:
        preview（安全拦截路径）→ subscribe 201 → move-to-new
        204 → rename 204 → OPML export（attachment + feed 在列）→
        import preview（1 new / 0 dup / 分类可见）→ import（added 1,
        categoryApplied true, categoriesCreated 1）→ unsubscribe
        ×2 204 → 基线还原（4 feeds，无残留分类）
Visual: 390/430/768（订阅页 + Add/OPML/Unsubscribe×2/Rename 对话框
        + 搜索空态）+ 1024/1280/1440（Settings→订阅与来源）+ dark +
        Escape/焦点 + console 零 error
```

### Known gaps

- preview 成功路径无法在 fake-IP 代理宿主环境 live 验证（离线测试
  覆盖；见 Gate 5 notes）；
- escape hatch 需服务端配置 `FRESHRSS_PUBLIC_URL`（当前 dev 未配置，
  显示诚实说明）；
- 移动端「添加订阅」全屏 Dialog 在本 Gate 以 a11y snapshot + 契约
  测试验证（Gate 2 遗留的截图验证项已在 Gate 3/5 的 390 实测中
  补齐）；
- OPML 导入对分类 move 失败容忍（订阅已加、`categoryApplied=false`
  如实上报），不自动重试；
- 预览的重复判定仅基于订阅地址精确匹配。

### 0014 handoff

- 0014 source discovery 产出 direct feed URL 后，直接复用本 milestone
  的 `POST /feed-preview` + `POST /subscriptions` pipeline →
  FreshRSS；不应也不需要第二套 subscribe 通道；
- `FreshRSSControlAdapter` 的窄接口与共享 session 模式可作为
  `RSSHubCatalogAdapter` / `RSSHubControlAdapter` 的实现参照；
- 设置中心「RSSHub 路由」入口已预留（planned · 0014 占位）。
