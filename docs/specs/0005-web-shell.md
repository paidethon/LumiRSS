# Spec 0005 — Web Shell

> 日期：2026-08-28
> 对应 PRD 阶段：Phase 3 — Reading Experience（首个里程碑）
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**

## Goal

第一次建立真正的 LumiRSS React Web 应用（`apps/web/`），使用现有 BFF
API 展示 Feed 与文章列表，打通完整链路：

```text
Browser → React → TanStack Query → relative /api/* 
        → Vite development proxy → FastAPI BFF :8000 
        → FreshRSSAdapter → FreshRSS
```

完成后，在浏览器打开 LumiRSS 可以：

```text
看到 LumiRSS Web Shell（三栏布局）
    ↓
看到真实 Feed（来自 GET /api/v1/feeds）
    ↓
看到真实 Entry（来自 GET /api/v1/entries）
    ↓
切换 All / Unread / Starred
    ↓
选择 Feed（含 All Feeds 恢复）
    ↓
点击"加载更多"（如果存在 nextCursor）
    ↓
点击文章进行 UI selection（右栏占位区响应）
```

0004 回答"后端能不能像一个 RSS Reader 一样工作？"，0005 回答
"**用户能不能第一次在浏览器里看到一个像 RSS Reader 的 LumiRSS？**"

0005 是 **Web application shell + feed/article list**，不是完整 RSS
Reader：正文阅读、状态修改 UI、Mobile/PWA 分别属于 0006 / 0007。

## Context — 这个阶段为什么存在（写给初学者）

### 0005 在整个项目中的位置

Phase 2（0002–0004）只用 curl 验证后端。没有任何用户界面，LumiRSS
就只是一个 API。Phase 3 从 0005 开始把这套 API 变成真正的产品：
第一个里程碑只搭"外壳"——布局、导航、列表、分页、选中，
**不碰正文和写操作**，让 Web 层在最小范围内先站稳。

### Server State vs UI State（本 Spec 最重要的概念）

前端有两种完全不同的"状态"：

```text
Server State（服务器状态）              UI State（界面状态）
─────────────────────────────          ─────────────────────────
来自 BFF 的真实数据                     只存在于用户本次操作
feeds / entries / nextCursor           当前点了哪个 view / feed / entry
会过期、需要重新获取                    立即生效、不需要请求
loading / error / cache                刷新后丢失完全可以接受
        ↓                                      ↓
  TanStack Query                        Zustand
```

为什么不能混？如果把 entries 复制进 Zustand，同一份数据就存在两份，
刷新、缓存、分页、重试都会出现"两本账"，不知道哪份是真的。所以：

> **TanStack Query = server state；Zustand = local UI state。**
> Zustand 禁止出现 feeds[]、entries[]、nextCursor、loading、error、
> 任何 server response cache。

### Vite 是什么？Vite Proxy 为什么不需要 CORS？

Vite = 开发服务器 + 构建工具（不是后端）。开发时浏览器访问
`http://localhost:5173`，React 代码里的 fetch 只写相对路径
`/api/v1/...`；Vite 在 `vite.config.ts` 里配置了 proxy，把匹配
`/api` 的请求原样转发给 `http://127.0.0.1:8000`（FastAPI）：

```text
Browser ──GET /api/v1/feeds──→ Vite :5173 ──转发──→ FastAPI :8000
```

对浏览器来说，请求始终发往 `localhost:5173` 自己（同源），
所以**没有跨域问题，不需要给 BFF 加 CORS**。未来生产环境换成
Caddy 做 `/api/*` 反代，是同一个模式，React 代码完全不用改。

### Query Key 为什么必须包含筛选条件？

```text
["entries", { view: "all",    feedUrl: null }]   ← 一个缓存
["entries", { view: "unread", feedUrl: null }]   ← 另一个缓存
["entries", { view: "unread", feedUrl: "https://…" }] ← 又一个
```

如果所有文章共用 `["entries"]` 一个 key，切到 Unread 时 TanStack
Query 会认为"数据我已经有了"，返回 All 的旧缓存，界面显示错误数据。
key 包含 scope = 不同筛选就是不同缓存，切换时自动重新加载。

### Cursor 为什么前端完全不解析？

`nextCursor` 是 BFF 生成的 opaque（不透明）字符串（内部是
`c1.` + base64url 包装的 FreshRSS continuation + scope）。前端唯一
正确的用法：**原样存起来，翻页时原样传回**。任何 decode/修改都会
把前端耦合到 BFF 内部格式上，BFF 一改版前端就崩。测试 B 会专门
验证 cursor 原样透传。

### useInfiniteQuery 为什么适合 Load More？

`useInfiniteQuery` 帮你管理"多页数据"：它记住每一页的结果
（`data.pages`），你只需要告诉它两件事——

```text
initialPageParam: null                // 第一页没有 cursor
getNextPageParam: (lastPage) =>
    lastPage.nextCursor ?? undefined  // 有 nextCursor 才有下一页
```

点击"加载更多"调 `fetchNextPage()`，它会自动把上一页的
`nextCursor` 作为下一页的 `pageParam` 传给 queryFn。不自己维护
pages 数组 / cursor 栈 / loadingNext 状态机——这些全是
useInfiniteQuery 已经解决的问题。

### `pnpm dev` 和 `pnpm build` 的区别？

`dev` 启动开发服务器：即时热更新、走 Vite proxy、源码不打包。
`build` 生成生产版本：TypeScript 检查 + 打包压缩输出到 `dist/`。
**dev 能跑 ≠ build 能过**（类型错误只在 build 时暴露），所以两个
都必须真实运行验收。

## Current verified behavior（从源码确认的真实 API Contract）

以下直接读自 `services/bff/src/lumirss/`（main.py / models.py /
cursor.py），**不是从旧聊天猜测**：

### GET /api/v1/feeds

```json
[{"title": "FreshRSS releases", "feedUrl": "https://…/feed.xml"}]
```

- 响应是**裸数组**（不是 `{items: […]}` envelope）；
- 每项恰好两个 string 字段：`title`、`feedUrl`；
- 没有 unread count（不存在 unread-count API——sidebar 禁止显示
  假的"123 unread"）。

### GET /api/v1/entries?view=…&feedUrl=…&cursor=…

```json
{
  "items": [
    {
      "entryRef": "e1.…",
      "title": "…",
      "feedTitle": "…",
      "author": null,
      "url": null,
      "publishedAt": null,
      "read": false,
      "starred": true
    }
  ],
  "nextCursor": "c1.…"
}
```

- `view`：枚举 `all` / `unread` / `starred`；未提供 = all；
- `feedUrl`：来自 feeds 接口的 feedUrl；可与 view 组合；
- `cursor`：opaque 字符串；可独立携带（不重复 view/feedUrl），
  也可与 view/feedUrl 同时携带但必须与 cursor scope 完全一致，
  否则 400 invalid_cursor。**前端策略：请求时始终显式携带与 query
  key 相同的 view（和 feedUrl）**，永远与 cursor scope 一致，从
  构造上规避 400；
- `nextCursor`：`null` = 没有更多页（不伪造、不省略字段）；
- 页大小固定 n=20（BFF 内部，前端不传 limit/pageSize）；
- `author` / `url` / `publishedAt` 可为 null；`title` / `feedTitle`
  缺失时 BFF 回退为 `""`；
- 列表**永远不含正文**（0003 契约）。

### 错误响应（BFF 统一格式）

```json
{"error": {"type": "invalid_cursor", "message": "…"}}
```

已知 error type：`configuration_error`(503)、
`authentication_error`(502)、`connection_error`(502)、
`upstream_error`(502)、`invalid_entry_reference`(400)、
`entry_not_found`(404)、`invalid_cursor`(400)。FastAPI 自身
validation 错误（如非法 view）返回 422，格式是 detail 数组
（**不是** error envelope）——API client 对两种形状都要容错。

### 0005 明确不调用的端点（写进边界，可从代码/Network 验证）

```text
GET   /api/v1/entries/{entryRef}        ← 0006 Reader Detail
PATCH /api/v1/entries/{entryRef}/state  ← 0006 状态操作 UI
```

API client 里根本不实现这两个函数，从源头杜绝 scope creep。

## Scope

只做：

1. 创建 `apps/web/`（pnpm + Vite react-ts 模板，清理 demo）；
2. Tailwind CSS v4（`@tailwindcss/vite` plugin）+ 极少 base styles；
3. Vite dev proxy：`/api` → `http://127.0.0.1:8000`；
4. `src/api/`：手写最小 TypeScript types + fetch client + ApiError；
5. `src/store/reader-ui.ts`：Zustand 最小 UI store；
6. 三栏 Web Shell：Sidebar / EntryList / ReaderPlaceholder；
7. TanStack Query：`useFeeds()` + `useEntries()`（useInfiniteQuery）；
8. Load More 分页按钮；
9. Entry selection（仅 UI，不 fetch detail）；
10. Vitest + React Testing Library 测试（Test A–L）；
11. lint / build / BFF regression / 真实 integration smoke / 文档。

## Non-goals（明确不做，做了就是 scope creep）

- **Reader Detail**：不调用 `GET /entries/{entryRef}`，不显示正文；
- **状态修改 UI**：不调用 PATCH，不做 star/unread 按钮、不做
  optimistic update / mutation rollback / cache patch（0006 再做）；
- **自动标记已读**：无任何写操作；
- Mobile/PWA/390px 布局/drawer/bottom nav（0007）；
- Category / folder / 分类筛选（0004 已 deferred，Feed 数据里即使
  有 category 信息也不顺手实现）；
- React Router / URL routing（`/article/...` 等，0006+ 再评估）；
- unread count（无 API，不造假数据，不从第一页计算总数）；
- 自动 infinite scroll / IntersectionObserver；
- localStorage / sessionStorage / IndexedDB / Zustand persist
  （刷新后回到 All + All Feeds + 无选中，可接受）；
- Search、Feed CRUD、AI、RSSHub、Caddy、production deployment；
- 给 BFF 加 CORS middleware（proxy 已解决同源）。

## 技术栈（冻结，不得替换）

```text
React + TypeScript + Vite（create-vite react-ts 模板，非 react-compiler-ts）
Tailwind CSS v4（@tailwindcss/vite plugin，不用旧式 postcss/tailwind.config.js）
TanStack Query（server state）
Zustand（UI state，不用 persist middleware）
fetch（不用 axios / OpenAPI generator / orval / GraphQL）
Vitest + React Testing Library + jest-dom + jsdom（测试）
```

禁止引入：Next.js / Nuxt / Vue / Svelte / Angular / Remix /
TanStack Start / Astro / Redux / MobX / SWR / Apollo / react-router /
axios / shadcn / radix / headlessui / lucide / date-fns / dayjs /
framer-motion / clsx / tailwind-merge / zod / Storybook / Playwright /
Cypress / MSW / Turborepo / Nx / Changesets / Lerna。

不建复杂 monorepo tooling；`apps/web/` 与 `services/bff/` 只是
清晰分离的两个目录。

## Package Manager 与目录

- **pnpm**（Build 前先检查 `node --version` / `pnpm --version`；
  Node 不满足当前 Vite 官方最低要求或 pnpm 不存在 → **停止并报告**，
  不自动升级 Node / 装 nvm / global install）；
- Web 独立放在 `apps/web/`，自带 `pnpm-lock.yaml`，**不生成第二个
  git repo**（模板自带的 `.gitignore` 合并进仓库现有约定）。

## 项目结构（上限，实际以模板为准）

```text
apps/web/
├── package.json
├── pnpm-lock.yaml
├── index.html
├── vite.config.ts          # React plugin + Tailwind plugin + /api proxy
│                           # + test 配置（jsdom + setupFiles）
├── tsconfig*.json          # 模板自带
├── eslint.config.js        # 模板自带（如实际使用）
├── src/
│   ├── main.tsx            # StrictMode → QueryClientProvider → App
│   ├── App.tsx             # 三栏 Grid 布局
│   ├── index.css           # @import "tailwindcss" + 极少 base styles
│   ├── api/
│   │   ├── client.ts       # getFeeds / getEntries + ApiError
│   │   └── types.ts        # Feed / EntryListItem / EntryListResponse /
│   │                       # ApiErrorResponse / EntryView
│   ├── store/
│   │   └── reader-ui.ts    # Zustand: view / selectedFeedUrl /
│   │                       # selectedEntryRef
│   ├── test/
│   │   └── setup.ts        # jest-dom + RTL cleanup（每个 test 后
│   │                       #   cleanup()；vite.config.ts 引用）
│   └── components/
│       ├── Sidebar.tsx
│       ├── EntryList.tsx
│       ├── EntryRow.tsx
│       └── ReaderPlaceholder.tsx
└── src/__tests__/          # 或等价测试布局，由 Build 时按模板最小确定
```

禁止为了"结构专业"创建：features/ domain/ entities/ use-cases/
repositories/ contexts/ providers/ layouts/ pages/ hooks/ utils/
constants/ services/ 等目录。当前 App 很小。

`main.tsx` 保持：StrictMode → QueryClientProvider → App，不建
多层 provider abstraction。

## Frontend Architecture

```text
Browser
  ↓
React (apps/web)
  ├── TanStack Query ←→ BFF server data（feeds / entries / pages）
  │      useFeeds()          key: ["feeds"]
  │      useEntries()        key: ["entries", {view, feedUrl}]
  │                          useInfiniteQuery + Load More
  └── Zustand ← UI selection
         view: "all" | "unread" | "starred"
         selectedFeedUrl: string | null
         selectedEntryRef: string | null
  ↓
relative /api/v1/*（fetch，无硬编码 localhost:8000）
  ↓
Vite dev proxy :5173 → /api → FastAPI :8000
  ↓
FreshRSSAdapter → FreshRSS
```

## API Client 设计

### types.ts（与真实 BFF Contract 一一对应，不加后端没有的字段）

```typescript
export type EntryView = "all" | "unread" | "starred"

export interface Feed {
  title: string
  feedUrl: string
}

export interface EntryListItem {
  entryRef: string
  title: string
  feedTitle: string
  author: string | null
  url: string | null
  publishedAt: string | null
  read: boolean
  starred: boolean
}

export interface EntryListResponse {
  items: EntryListItem[]
  nextCursor: string | null
}

export interface ApiErrorResponse {
  error: { type: string; message: string }
}
```

### client.ts

```typescript
const API_BASE = "/api/v1"

export class ApiError extends Error {
  readonly status: number
  readonly type: string
  readonly message: string
}

export async function getFeeds(signal?: AbortSignal): Promise<Feed[]>

export async function getEntries(params: {
  view: EntryView
  feedUrl: string | null
  cursor?: string | null
}, signal?: AbortSignal): Promise<EntryListResponse>
```

规则：

- **只实现这两个函数**（detail/state 端点不出现）；
- 统一 base `/api/v1`，组件里禁止散落 `fetch("/api/v1/…")`；
- `getEntries` 构造 query：`view` 始终显式携带；`feedUrl` 仅非 null
  时携带；`cursor` 仅存在时携带，且**作为 opaque string 原样传递，
  绝不 decode/修改**；
- 响应非 2xx → 尝试解析 `{"error": {type, message}}`（FastAPI 422
  的 detail 形状也要容错）→ 解析失败用安全 fallback message →
  抛 `ApiError`。UI 永远不显示 stack trace / raw HTML / internal
  exception；
- **Cancellation 不算错误**：进入函数时 `signal?.aborted === true`，
  或 fetch 抛出的 `AbortError` → **原样 rethrow 该 cancellation
  error，不包装成 `ApiError`**，不进入普通 network retry / error
  UI（TanStack Query 对被取消的 query 有自己的处理，取消不应触发
  error state）；
- **只有真正的网络失败**（fetch reject 且非 abort）→ 抛
  `ApiError(status=0)`；
- queryFn 提供的 `AbortSignal` 透传给 fetch（快速切换 view/feed
  时旧请求自动取消，不自建 cancellation manager）。

## Zustand Store 设计

```typescript
interface ReaderUiState {
  view: EntryView
  selectedFeedUrl: string | null
  selectedEntryRef: string | null
  selectView(view: EntryView): void
  selectFeed(feedUrl: string | null): void   // null = All Feeds
  selectEntry(entryRef: string | null): void
}
```

- 初始值：`view: "all"`，`selectedFeedUrl: null`，
  `selectedEntryRef: null`；
- `selectView` / `selectFeed` 改变 scope 时**必须清空
  selectedEntryRef**（旧 selection 可能已不属于新列表）；
- 点击同一个 view/feed 再次点击：保持幂等（同值 no-op 或等价
  行为，不产生副作用）；
- **禁止**存：feeds[]、entries[]、nextCursor、loading、error、
  server response cache、完整 Entry object（右栏需要 title/feedTitle
  时用 `selectedEntryRef` 在 TanStack Query 当前 pages 里 `find()`）。

## TanStack Query 设计

### QueryClient

应用根部一个实例（`main.tsx` 创建）。retry 采用**默认行为**
（3 次、带退避），不在 0005 自建 retry framework；staleTime /
refetchOnWindowFocus 等保持默认，除非 Build 中发现真实问题再最小调整
（Spec 记录最终决定）。

### useFeeds()

```text
GET /api/v1/feeds
key: ["feeds"]
```

### useEntries(view, feedUrl)

```text
GET /api/v1/entries
key: ["entries", { view, feedUrl }]
useInfiniteQuery:
  initialPageParam: null
  queryFn({ pageParam })  → getEntries({view, feedUrl, cursor: pageParam}, signal)
  getNextPageParam(lastPage) → lastPage.nextCursor ?? undefined
```

- 切换 view/feedUrl → query key 变化 → 自动加载新列表（旧请求经
  AbortSignal 取消）；
- 组件渲染用 `data.pages.flatMap(p => p.items)`；
- 是否封装 `useFeeds`/`useEntries` hook：**是**（Sidebar 与
  EntryList 各自需要完整 query 配置，封装避免重复；但只此两个，
  不做一行 wrapper 大全）。

## UI 信息架构（Desktop-first 三栏）

```text
┌──────────────┬──────────────────────┬─────────────────────────────┐
│  Navigation  │     Entry List       │        Reader Area          │
│  (240px 固定)│    (400px 固定)      │      (剩余宽度, min 0)       │
│              │                      │                             │
│  LumiRSS     │  当前 scope 标题      │   无选中:                    │
│  流光阅源     │  ──────────────      │     "选择一篇文章开始阅读"    │
│              │  Entry Row           │                             │
│  All         │  Entry Row           │   已选中:                    │
│  Unread      │  Entry Row           │     title + feedTitle       │
│  Starred     │  …                   │     (来自 Query cache 查找)  │
│  ──────────  │                      │                             │
│  All Feeds   │  [加载更多] /         │   0006: Reader Detail       │
│  feed 1      │  "已经到底了"         │                             │
│  feed 2…     │                      │                             │
└──────────────┴──────────────────────┴─────────────────────────────┘
```

- 布局：CSS Grid（`grid-cols-[240px_400px_1fr]` 等价实现）；
- 高度：`100dvh`，三栏各自 `overflow-y-auto`，页面整体不出现
  纵向滚动条把 sidebar 卷走；
- 不做 resizable panels / drag handles / layout persistence；
- 1024px 窄屏下 Entry List 可收窄（如 `380px`），不要求 390px
  mobile 布局；用一条简单 media query 防止灾难性 overflow 即可，
  **不**开始 mobile redesign。

### Sidebar

- 顶部：`LumiRSS` + 小字 `流光阅源`（typography 品牌，无 logo 图片）；
- Views：All / Unread / Starred（`<button>`，`aria-current` 标记当前
  view）；**不显示 unread count**（无 API，不造假）；
- Feeds 区：`All Feeds` + 真实 feed 列表（来自 `["feeds"]` query）；
  点击 feed → `selectFeed(feed.feedUrl)`，**保留当前 view**（可表达
  "某 Feed 的未读/收藏"）；点击 All Feeds → `selectFeed(null)`；
- feed 项当前选中态有视觉表现（背景/边框，不只靠颜色）；
- Feeds **loading**：简单 Loading placeholder（纯文字或几行
  skeleton，只选一种，不引入 skeleton library）；
- Feeds **error**：feed 区显示 `订阅加载失败` + `重试` 按钮
  （`refetch()`）；All/Unread/Starred 导航仍然可用，**不白屏**；
- 不做 Category / folder 分组。

### Entry List

- Header：显示当前 scope —— 无 feed 时显示 view 名（All / Unread /
  Starred），有 feed 时显示 feed title，副标题轻量表达组合
  （如 `未读 · FreshRSS releases`），不做复杂 breadcrumb；
- **loading**（首次加载）：5–8 条 lightweight skeleton rows，禁白屏；
- **error**：`文章加载失败` + ApiError 安全 message + `重试` 按钮，
  App 不崩溃，不显示堆栈；
- **empty**（成功但 items=[]）：`这里还没有文章`（可按 view 轻量
  区分文案，如 Starred 空时"还没有收藏文章"）；**0 条不是错误**；
- **fetchNextPage 中**：按钮显示 `加载中…` 并 disabled。

### Entry Row

每条至少显示：

```text
title（unread: 标题明显 + 小圆点 indicator；read: 标题弱化）
feedTitle
author（如有）
publishedAt（Intl.DateTimeFormat；缺失 → "—"，绝不出现 Invalid Date）
starred: "★" 或极小 inline SVG indicator
```

- 整行是 `<button>`（键盘可操作、focus-visible 清楚），点击 →
  `selectEntry(item.entryRef)`；
- 选中行有明确 selected style（背景 + 边框，不只靠颜色）；
- **不显示** contentText / 正文；
- **不做** star/unread 点击写状态（只展示状态 indicator，0005 只读）。

### Load More（分页 UX）

- 有 `nextCursor`（即 `hasNextPage`）才显示 `加载更多` 按钮；
- fetching 中：`加载中…` + disabled；
- 没有下一页：显示轻量 `已经到底了` 或不显示（二选一，不做复杂设计）；
- 不做自动 infinite scroll / IntersectionObserver。

### ReaderPlaceholder（右栏）

- 无选中：`选择一篇文章开始阅读` + 简洁说明；
- 已选中：显示至少 `title` + `feedTitle` —— 数据来源：
  `selectedEntryRef` → 在当前 `data.pages` 中 `find()`；
  **不**把完整 Entry object 存进 Zustand，**不**调用 Detail API。

## Visual Direction

```text
clean / calm / reading-first / modern（不是 enterprise dashboard）
浅色主题 · 中性灰背景 · 白色阅读区域 · 细边框
合理留白 · 克制蓝色 accent · 圆角适中 · 无强烈阴影
```

- 字体：system-ui 栈（system-ui / -apple-system /
  BlinkMacSystemFont / Segoe UI / sans-serif），不用 Google Fonts /
  字体 CDN / 字体资产；
- 图标：不需要 icon library；如确实需要用极少量 inline SVG 或文本
  符号（★ / ●）；
- 无 logo / illustration / background image / hero graphics——
  品牌先用 typography；
- 不复制 Folo 等产品的具体 UI。

## Accessibility（最小要求）

- navigation 与 entry row 全部用 `<button>`，不把可点击 div 当
  button；
- entry selection 键盘可操作（button 天然支持 Enter/Space）；
- selected state 有视觉表现；`aria-current`（view/feed）/
  `aria-pressed`（如适用）等最小语义；
- `:focus-visible` 清楚；不只靠颜色表达 unread/selected（圆点 /
  边框 / 字重并用）；
- loading / error 文字可读；不引入 accessibility framework。

## Date formatting

浏览器原生 `Intl.DateTimeFormat`（如
`new Intl.DateTimeFormat("zh-CN", {year, month, day, hour, minute})`
具体格式 Build 时定）。**不新增** dayjs / date-fns / moment。
`publishedAt` 为 null → 显示 `—` 或不显示，绝不出现 Invalid Date。

## Dependencies（逐个说明用途）

### runtime（4）

| 包 | 用途 |
| --- | --- |
| `react` / `react-dom` | UI 库本体（冻结架构指定，当前稳定版） |
| `@tanstack/react-query` | server state：feeds/entries 请求、缓存、loading/error、无限分页 |
| `zustand` | 最小 typed UI store：view/feed/entry selection |

### build / UI（5）

| 包 | 用途 |
| --- | --- |
| `vite` | dev server + production build |
| `typescript` | 类型检查（build 的一部分） |
| `@vitejs/plugin-react` | Vite 官方 React 插件（模板自带） |
| `tailwindcss` | 样式（冻结架构指定） |
| `@tailwindcss/vite` | Tailwind v4 官方 Vite plugin（代替旧式 postcss 配置） |

### 测试（4，逐个说明为什么需要）

| 包 | 为什么需要 |
| --- | --- |
| `vitest` | Vite 生态原生测试 runner（与 Vite 共享 transform 配置；任务指定最小合理方案，不用 Jest 双栈） |
| `jsdom` | 组件测试需要浏览器 DOM 环境（无头浏览器过重，0005 无 E2E） |
| `@testing-library/react` | 以用户视角渲染/查询组件（任务 Test E–L 需要） |
| `@testing-library/jest-dom` | 语义化 DOM 断言（toBeInTheDocument 等，错误信息可读） |

`@types/react` / `@types/react-dom` 及模板自带的 eslint 系列依赖
作为**模板 dev dependencies** 按模板实际保留（不计入上面 5 个的
计数）。**除此之外的任何新增依赖必须先停下请批准。**

## Testing strategy

- 全部测试无真实网络：`vi.stubGlobal("fetch", …)` mock fetch
  （组件测试通过 QueryClient 真实渲染，不走 MSW——不引入 MSW）；
- 测试 QueryClient 用独立实例（`retry: false` 让错误立即可断言）。

### Vitest / RTL 配置（最小，不新增配置文件框架层）

- **不新建 `vitest.config.ts`**：在现有 `vite.config.ts` 顶部加
  `/// <reference types="vitest/config" />`，最小增加 `test` 字段：

```typescript
// vite.config.ts（概念）
/// <reference types="vitest/config" />
export default defineConfig({
  // …plugins / server.proxy…
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
})
```

- 新增 `src/test/setup.ts`，内容语义：

```typescript
import "@testing-library/jest-dom/vitest"
import { cleanup } from "@testing-library/react"
import { afterEach } from "vitest"

afterEach(() => {
  cleanup()
})
```

- **Vitest globals 保持默认 false**：测试文件显式
  `import { describe, it, expect, vi } from "vitest"`；
- **0 additional dependencies**（jsdom / RTL / jest-dom 已在依赖
  清单中）；不为测试再新增任何配置文件或框架层。

### 测试清单（任务 Test A–L，数量由行为自然决定，不凑数）

| 测试 | 验证内容 |
| --- | --- |
| **A — API client base** | mock fetch；`getFeeds()` 实际请求 `/api/v1/feeds`（相对路径，无 localhost:8000） |
| **B — entries query params** | view=all/unread/starred、feedUrl、cursor 正确转成 query string；**cursor 作为 opaque string 传递**：使用合法、URL-safe 的 fake cursor（如 `c1.fake-_cursor_0005`），请求后用 `URL.searchParams.get("cursor")` 读取并断言 **=== 输入值**；前端不得 base64 decode、parse、修改 cursor。`URLSearchParams` 对 feedUrl/query string 的 percent encoding 属正常 HTTP transport，不等于 LumiRSS cursor decode |
| **C — API error** | BFF 4xx/5xx（error envelope 形状 + 非 JSON 形状如 HTML/422 detail）→ 转成安全 ApiError（含 status/type/message），不泄漏 raw body；**真正的网络失败 → status=0 ApiError**；**预先 abort 的 signal / mock fetch 抛 AbortError → 原样 rethrow cancellation error，不包装成 status=0 ApiError，不进入 error UI** |
| **D — UI store** | selectView / selectFeed / selectEntry 各自生效；**切 view 或 feed → selectedEntryRef 清空**；selectEntry 不影响 view/feed |
| **E — Shell loading** | feeds/entries pending 时存在 loading UI（sidebar placeholder + 列表 skeleton） |
| **F — Entry list 渲染** | fake BFF 返回 2 entries → 真实渲染 title / feedTitle / read-unread indicator / starred indicator；**正文不出现**（列表数据里根本没有 contentText，类型层也断言） |
| **G — Empty** | items=[] → 显示 empty state，不是报错 |
| **H — Error** | entries 请求失败 → error state + 重试按钮；App 不崩溃 |
| **I — View 切换** | 点击 Unread → 后续 entries 请求带 `view=unread`；点击 Starred → `view=starred` |
| **J — Feed 切换** | 点击 feed → 请求带 `feedUrl=<selected>`；点击 All Feeds → 恢复无 feedUrl |
| **K — Entry selection** | 点击 entry → selectedEntryRef 改变；row 有 selected UI；ReaderPlaceholder 显示该 entry 的 title/feedTitle；**断言 fetch 只被调用于 /feeds 和 /entries（不出现 /entries/{ref} detail 请求）** |
| **L — Load more** | 第一页 nextCursor="c1.fake…" → 显示加载更多 → 点击 → 下一次请求 `cursor=c1.fake…` 原样 → 两页 items 都渲染；无 nextCursor → 无按钮/显示到底 |

## Acceptance Criteria

- **AC1 — Branch**：所有修改位于 `feat/0005-web-shell`。
- **AC2 — Web project**：`apps/web` 存在，React + TypeScript + Vite
  可启动（`pnpm dev` 真实运行成功）。
- **AC3 — Frozen stack**：实际使用 React / TypeScript / Vite /
  Tailwind / TanStack Query / Zustand；无未经批准的替代框架。
- **AC4 — Development proxy**：React runtime API 只使用相对
  `/api/v1/*`；Vite dev proxy 转发 BFF；runtime API client 无硬编码
  `localhost:8000`；**BFF 不新增 CORS**（`services/bff` 零修改）。
- **AC5 — Real feeds**：Sidebar 真实显示 `GET /api/v1/feeds` 返回的
  Feed（真实 integration smoke 验证）。
- **AC6 — Real entries**：主列表真实显示 `GET /api/v1/entries` 数据。
- **AC7 — View filters**：All / Unread / Starred 切换后请求真实对应
  view。
- **AC8 — Feed filter**：选择真实 Feed 的 `feedUrl` 正确影响 Entries
  Query；All Feeds 可恢复。
- **AC9 — Pagination**：使用 nextCursor + useInfiniteQuery 实现 Load
  More；frontend 不解析 cursor。
- **AC10 — Query/Zustand boundary**：feeds / entries / pages /
  loading / errors 只由 TanStack Query 管理；Zustand 不复制。
- **AC11 — UI state**：Zustand 只管理 view / selectedFeedUrl /
  selectedEntryRef（或等价最小 UI state）。
- **AC12 — List states**：loading / empty / error / success /
  fetch-next-page 均有合理 UI。
- **AC13 — Entry row**：真实显示 title / feedTitle / publishedAt /
  read / starred，nullable 字段正确处理（无 Invalid Date、无崩溃）。
- **AC14 — Selection**：点击文章 → selectedEntryRef 变化、row
  selected style 正常、右栏 placeholder 响应；**0005 不 fetch
  Detail**（可从 API client 代码与 Network/测试断言双重确认）。
- **AC15 — No reader scope creep**：无 contentText detail、无
  dangerouslySetInnerHTML、无 reader rendering、无 state mutation UI、
  无 automatic mark-read。
- **AC16 — Automated tests**：新增 Web 自动化测试实际全绿（报告真实
  `XX passed`）。
- **AC17 — Quality gates**：实际通过 `pnpm lint` 与 `pnpm build`
  （Vite production build 成功；不是只跑 dev）。
- **AC18 — BFF regression**：0002–0004 全部现有 backend tests 无
  regression——`cd services/bff && uv run pytest` 全绿（当前
  baseline 可记录为 120 passed，仅作参考；Build 报告以实际运行的
  `XX passed` 为准，**"恰好 120"本身不是功能 AC**；0005 不应也无
  法修改 BFF）。
- **AC19 — Real integration**：真实 Vite Web → /api proxy → FastAPI
  → FreshRSS 链路成功；Feed + Entries 在真实 UI 可见；浏览器
  Network 只见 `/api/v1/...` 相对路径请求。
- **AC20 — Visual**：1440 / 1280 / 1024 桌面布局可用（sidebar 列表
  可读、右栏合理、无意外横向滚动、active/selected 可辨认、
  loading/error/empty 不破版）。如当前 Agent 环境无视觉浏览器：
  **明确标记 UNVERIFIED 并要求用户人工确认，不假装 PASS**。
- **AC21 — Dependencies**：无未经批准的 Router / Axios / UI
  framework / icon package / date library / animation library /
  OpenAPI generator；无 unused dependency。
- **AC22 — Scope**：未实现 Reader Detail / Mobile / PWA / Category /
  Search / Feed CRUD / AI / RSSHub / Caddy / Production。

## Tasks（Build 顺序，批准后严格逐步执行，每步完成即验证）

1. **环境检查**：`node --version` / `pnpm --version`（不满足 →
   停止报告；不自动升级/安装）；
2. 创建 `apps/web`：`pnpm create vite . --template react-ts`（或等价
   官方方式）；确认不生成第二个 git repo；
3. 清理模板 demo（默认页面/counter/logo asset，Diff 可解释）；
4. 配置 Tailwind v4：`@tailwindcss/vite` + `index.css`
   `@import "tailwindcss"` + 极少 base styles（系统字体栈、CSS
   variables）；删除模板自带 App.css 等；
5. 配置 `vite.config.ts`：`/api` → `http://127.0.0.1:8000` proxy
   （官方 `server.proxy` 写法）+ `test` 配置（`environment: "jsdom"`
   + `setupFiles: "./src/test/setup.ts"`）+ 新建
   `src/test/setup.ts`（jest-dom import + RTL cleanup）；
6. 建 `src/api/types.ts` + `client.ts`（ApiError、getFeeds、
   getEntries、AbortSignal 透传 + cancellation rethrow 不包装
   ApiError）→ **Test A / B / C**；
7. 建 `main.tsx` QueryClientProvider（StrictMode）；
8. 建 `src/store/reader-ui.ts` → **Test D**；
9. 实现 Sidebar（useFeeds + All/Unread/Starred + feed selection +
   loading/error state）；
10. 实现 EntryList（useEntries useInfiniteQuery + loading/error/
    empty）；
11. 实现 EntryRow（read/starred/publishedAt 显示）；
12. Load More 按钮（hasNextPage / fetchNextPage / 到底提示）；
13. Entry selection + ReaderPlaceholder（Query cache find）；
14. UI tests 补全 → **Test E–L**；
15. 全量 `pnpm test`（vitest run）；
16. `pnpm lint`；
17. `pnpm build`（production build 必须真实成功）；
18. BFF regression：`cd services/bff && uv run pytest`（全绿即
    通过；报告实际 `XX passed`，baseline 参考 120；BFF 零修改）；
19. Real integration smoke：启动 BFF（uvicorn :8000）+ Web
    （pnpm dev）；确认 proxy 链路、真实 feeds/entries、view/feed
    切换、Load More（如真实数据 ≤ 20 条则如实记录
    "Real nextCursor unavailable because current dataset has <= 20
    entries"，**不制造数据**）、entry selection；
20. Visual review：1440 / 1280 / 1024（如环境有 Browser/Preview 则
    实际检查，否则明确 UNVERIFIED + 请用户人工打开
    `http://localhost:<port>`）；
21. README / PROJECT_STATE 更新（只写实际运行成功的命令；不写未实现
    的 Reader/PWA/Caddy/production）；
22. Progress Board / devlog 0005（`docs/devlog/0005-web-shell.md`）；
23. Secret / scope scan（tracked + untracked-not-ignored：无
    FRESHRSS_* / token / Authorization header / .env 泄漏；确认
    node_modules/ 与 dist/ 未进 git）；
24. 最终 git 检查（branch / status / diff --stat / diff --check /
    diff）→ **停在工作区等待人工 Review**（不 commit / push / PR）。

## Verification

```text
Frontend:  cd apps/web && pnpm test && pnpm lint && pnpm build
Backend:   cd services/bff && uv run pytest          # 全绿（报告实际 XX passed）
Git:       git branch --show-current                  # feat/0005-web-shell
           git status --short --branch                 # 仅预期文件
           git diff --stat / --check /                 # 无越界、无空白错误
Real:      BFF + Vite dev 真实链路 smoke（AC19）
Visual:    1440 / 1280 / 1024（AC20，无浏览器则 UNVERIFIED）
Secret:    扫描零命中（含 Authorization header 模式）
```

## Error 处理原则（遇到问题时）

先判断问题层（Node / pnpm / Vite / Tailwind / TypeScript / React /
TanStack Query / Zustand / Vite proxy / BFF API / CSS / tests /
network），按"现象 → 证据 → 问题层 → 原因 → 最小修复"报告。
**frontend fetch 失败 ≠ 改 FastAPI**：出现 CORS 先检查 React 是否
错误直连 `localhost:8000`。pnpm install 网络/registry 失败：不换
package manager、不改系统代理、不换随机 mirror，先报告问题层与
证据，利用现有 cache 重试需说明理由后再做。

## Documentation updates（AC 全过后单独做）

- `README.md`：Web development prerequisites / BFF start / Web
  start / Web tests / lint / build（只写实际运行成功的命令）；
- `docs/PROJECT_STATE.md`：Implemented 增加 Web Shell 各项；
  Current → Phase 3 — Reading Experience；Next → 0006 — Reader；
- `docs/progress/project-data.js`：0005 → completed（填
  implemented/acceptance/problems/learned + devlog 链接）、0006 →
  next、currentMilestoneId → "0006"、updatedAt；**Phase 3 保持
  current，不把整个 Reading Experience 标 completed**；
- `docs/devlog/0005-web-shell.md`：Status / Goal / Frontend
  architecture / Why Query vs Zustand / Vite proxy / UI 信息架构 /
  Actual dependencies / Actual commands / Tests / Build / Real BFF
  integration / Visual verification / Problems / Solutions /
  What I learned / Next milestone（不含 secret、node_modules 输出、
  AI internal reasoning、完整文章正文）。

## Risks / Unknowns

- **Node / pnpm 版本**：Build 第 1 步检查；不满足 → 停止报告
  （不自动升级）；
- **pnpm install 网络**：China 网络下可能慢/失败 → 报告后重试，
  不改系统配置、不换 mirror/package manager；
- **模板差异**：create-vite 当前版本的文件布局（eslint.config.js、
  tsconfig 结构）以实际生成为准，Spec 的结构表是上限不是死命令；
  有出入时在 Build 报告中说明；
- **真实数据 ≤ 20 条**：Load More 无法真实触发 → 如实记录，
  自动测试（Test L）覆盖行为，不制造数据；
- **视觉验证**：取决于当前环境是否有 Browser/Preview；没有则 AC20
  标 UNVERIFIED 并请用户人工确认，**不假装检查过**。

---

**本 Spec 为 Draft。在用户明确回复"批准 Spec，可以开始 Build"之前，
不修改任何仓库文件（本 Spec 自身除外）、不安装依赖、不运行脚手架、
不做任何 Build 步骤。**
