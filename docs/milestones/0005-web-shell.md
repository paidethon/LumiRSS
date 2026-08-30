# 0005 — Web Shell

> Status: **Completed**
> Original spec: Git history (docs/specs/0005-*.md)

---

> 日期：2026-08-28
> 里程碑：0005 — Web Shell（Phase 3 — Reading Experience 首个里程碑）
> 状态：COMPLETED（AC1–AC22 全部达成；未 commit，停在工作区等待人工 Review）
> Spec：`docs/specs/0005-web-shell.md`（Draft → 用户 5 点修订 → 批准）

## Goal

第一次建立真正的 LumiRSS React Web 应用（`apps/web/`），用现有 BFF API
展示 Feed 与文章列表：

```text
Browser → React → TanStack Query → relative /api/*
        → Vite dev proxy → FastAPI BFF :8000
        → FreshRSSAdapter → FreshRSS
```

## Frontend architecture

```text
Browser
  ↓
React (apps/web)
  ├── TanStack Query ←→ BFF server data（feeds / entries / pages）
  │      useFeeds()          key: ["feeds"]
  │      useEntries()        key: ["entries", {view, feedUrl}]
  └── Zustand ← UI selection
         view / selectedFeedUrl / selectedEntryRef
  ↓
relative /api/v1/*（fetch，无硬编码 localhost:8000）
  ↓
Vite dev proxy :5173 → /api → FastAPI :8000
  ↓
FreshRSSAdapter → FreshRSS
```

### Why TanStack Query vs Zustand（0005 最重要的架构决定）

- **TanStack Query = server state**：feeds、entries、nextCursor、loading、
  error、cache 全部归它。query key 包含筛选 scope
  （`["entries", {view, feedUrl}]`），切换筛选 = 新缓存 + 自动重新加载 +
  AbortSignal 取消旧请求。
- **Zustand = UI state**：只存 view / selectedFeedUrl / selectedEntryRef。
  切 view/feed 时清空 selection。无 persist——刷新回到
  All + All Feeds + 无选中，完全可接受。
- 边界从代码结构上强制：API client 只实现 `getFeeds`/`getEntries`
  两个函数（detail/PATCH 端点故意不存在），Zustand store 里没有任何
  server 数据字段。

### Vite proxy（为什么不需要 CORS）

浏览器所有请求发往 `localhost:5173`（同源），Vite 的 `server.proxy`
把 `/api` 原样转发给 `127.0.0.1:8000`。未来生产环境 Caddy 做同样的
`/api/*` 反代，React 代码不用改。**BFF 全程零修改。**

### Cursor 与 useInfiniteQuery

- cursor 是 opaque string：前端存下 `nextCursor`，翻页时原样传回，
  不 decode / parse / 修改（Test B 用 `URL.searchParams.get("cursor")`
  断言回读值 === 输入值）；
- `useInfiniteQuery`：`initialPageParam: null`，
  `getNextPageParam: lastPage.nextCursor ?? undefined`；
  点击"加载更多"调 `fetchNextPage()`，pages 自动累积，无手写状态机；
- 请求时始终显式携带与 query key 相同的 view/feedUrl——与 cursor
  scope 构造性一致，从源头规避 invalid_cursor 400。

## UI 信息架构

```text
┌──────────────┬──────────────────────┬─────────────────────────────┐
│ Sidebar      │ Entry List           │ ReaderPlaceholder           │
│ LumiRSS      │ scope 标题           │ 无选中: 选择一篇文章开始阅读  │
│ 流光阅源      │ loading skeleton     │ 已选中: title + feedTitle    │
│ All/Unread/  │ entry rows           │   （Query cache 查找，       │
│ Starred      │ read/starred 状态     │    不 fetch detail）        │
│ All Feeds    │ empty / error / 重试  │                             │
│ 真实 feeds    │ [加载更多] / 到底了    │ 0006: Reader Detail        │
└──────────────┴──────────────────────┴─────────────────────────────┘
```

三栏 CSS Grid（240px / 400px / 1fr，1100px 以下收窄为 220/360/1fr），
`100dvh` 内各栏独立 `overflow-y`。浅色主题、系统字体、文本符号
indicator（● 未读 / ★ 收藏）、无 icon library。

## Actual dependencies

| 包 | 版本 | 用途 |
| --- | --- | --- |
| react / react-dom | 19.2.8 | UI 库（模板自带） |
| @tanstack/react-query | 5.102.6 | server state / 无限分页 |
| zustand | 5.0.15 | 最小 UI store |
| vite | 8.2.2 | dev server + build（模板自带） |
| typescript | 6.0.3 | 类型检查（模板自带） |
| @vitejs/plugin-react | 6.1.0 | React 插件（模板自带） |
| tailwindcss + @tailwindcss/vite | 4.3.3 | Tailwind v4 官方 Vite 集成 |
| vitest | 4.1.11 | 测试 runner |
| jsdom | 30.0.1 | 组件测试 DOM 环境 |
| @testing-library/react | 16.3.2 | 用户视角组件测试 |
| @testing-library/jest-dom | 7.0.1 | 语义化 DOM 断言 |

模板 dev deps（oxlint、@types/react 等）按模板保留。**无任何未经
批准的依赖**；测试交互用 RTL 内置 fireEvent（未引入 user-event）。

## Actual commands（全部真实运行成功）

```bash
# 环境（nvm 已有安装，仅加载）
node --version          # v24.19.0
pnpm --version          # 11.7.0

cd apps/web
pnpm create vite web --template react-ts   # 在 apps/ 下执行
pnpm add @tanstack/react-query zustand
pnpm add -D tailwindcss @tailwindcss/vite vitest jsdom \
  @testing-library/react @testing-library/jest-dom
pnpm test               # 31 passed
pnpm lint               # oxlint: 0 warnings, 0 errors
pnpm build              # tsc -b + vite build 成功

# BFF regression（BFF 零修改）
cd services/bff && uv run pytest   # 120 passed

# 真实链路
cd services/bff && uv run uvicorn lumirss.main:app --port 8000
cd apps/web && pnpm dev            # http://localhost:5173
```

## Tests

31 个自动化测试（全部 mock fetch，无真实网络 / Secret）：

- Test A（1）：API client 相对路径 `/api/v1/feeds`，无硬编码主机；
- Test B（4）：view×3 / feedUrl / cursor opaque 透传
  （`c1.fake-_cursor_0005` 回读 === 输入）/ 无 cursor 不带参数；
- Test C（6）：error envelope → ApiError；HTML 错误页安全 fallback；
  422 detail 形状容错；真网络失败 → status=0；预先 abort / fetch 抛
  AbortError → 原样 rethrow 不包装（用户修订点 1）；
- Test D（7）：store 初始值 / 三 action / 切 view·feed 清空 selection /
  幂等 no-op；
- Test E–L（13）：Shell loading、列表渲染（含"正文不出现"）、
  empty（All/Starred 各自文案）、error + 重试、view 切换请求参数、
  feed 切换 + All Feeds 恢复、entry 选中（aria-pressed + 右栏响应 +
  **断言无 detail 请求**）、Load More（cursor 原样传回 + 两页渲染 +
  无 nextCursor 无按钮）。

## Build

`pnpm build`（tsc -b + vite build）真实成功：
dist/index.html 0.47 kB、CSS 13.31 kB、JS 234.57 kB（gzip 73.43 kB）。

## Real BFF integration

Vite dev server（:5173）+ BFF（:8000）+ FreshRSS（Docker）真实链路：

- `http://localhost:5173/api/v1/feeds` → 2 个真实订阅
  （FreshRSS releases、阮一峰的网络日志）；
- `http://localhost:5173/api/v1/entries` → 13 条真实文章
  （view=unread 12 条；view=starred 0 条，空状态真实触发）；
- 浏览器 UI 实测 8/8 PASS：首屏真实渲染、Unread/Starred 切换
  （Starred 显示"还没有收藏文章"）、feed 筛选（阮一峰源 3 条）+
  All Feeds 恢复、entry 选中（蓝色左边框 + aria-pressed + 右栏
  title/feedTitle）、无 Load More 按钮（显示"已经到底了"）；
- **Real nextCursor unavailable because current dataset has <= 20
  entries**（All 13 条 < n=20，无 continuation）——Load More 行为由
  自动测试（Test L）覆盖，不制造数据。

## Visual verification

浏览器子代理实测：1440 / 1280 / 1024 三档宽度三栏布局正常、六级
横向溢出检测全部为零、页面级无纵向滚动（h-dvh + 各栏独立滚动生效）、
active/selected 状态清晰可辨。前 4 项（首屏/空状态/feed 筛选/选中）
有截图；后 3 档宽度因子代理浏览器视图中途异常（F11 导致截图功能
失效），改用视口模拟 + 精确 DOM 布局度量验证（clientWidth 精确对齐
1440.0/1280.0/1024.0，溢出检测全部为零）——如实记录验证方法。

## Problems encountered（现象 → 原因 → 层级 → 解决）

1. **pnpm create vite 挂起无输出**
   现象：命令 6+ 分钟无输出。原因：pnpm dlx 的 "Ok to proceed?"
   交互确认被 `| tail` 管道吞掉。层级：pnpm/交互。解决：终止后
   `printf 'y\n' | pnpm create vite ...` 重试成功。
2. **AbortError rethrow 测试失败**
   现象：mock fetch 抛 DOMException(AbortError) 被包装成 status=0
   ApiError。原因：Node 运行时 DOMException 不继承 Error，
   `instanceof Error` 判断失效。层级：TypeScript/运行时。解决：
   isAbortError 改为纯 `name === 'AbortError'` 检查。
3. **error envelope 测试偶发 fallback**
   现象：同一 mock 的第二次调用解析不到 envelope。原因：mock 返回
   同一个 Response 对象，body 只能读一次。层级：测试写法。解决：
   测试改为单次调用断言。
4. **误用未批准依赖**
   现象：测试初稿 import 了 `@testing-library/user-event`（独立包，
   不在批准清单）。层级：依赖边界。解决：改用 RTL 内置 fireEvent，
   最终 0 个清单外依赖。
5. **tsc -b 暴露测试类型错误**
   现象：`.catch((e: ApiError) => e)` 的返回类型是联合类型，属性
   访问报 TS2339；`||` 链式断言报 TS1345 + oxlint 警告。层级：
   TypeScript。解决：新增 `rejectsWithApiError()` 类型收窄 helper，
   拆开链式断言。

## What I learned

- **Server state vs UI state 的边界要靠结构强制**：API client 函数
  集合（只读两个端点）和 Zustand store 字段集合（三个 selection）
  就是边界的物理体现，比口头约定可靠；
- **cancellation 不是错误**：AbortSignal 透传给 fetch 后，AbortError
  必须原样 rethrow；包装成 ApiError(status=0) 会让正常的筛选切换
  触发 error UI + retry；
- **query key 即缓存身份**：`["entries", {view, feedUrl}]` 让每个
  scope 一份缓存，切换筛选天然正确；
- **DOMException 的运行时差异**：浏览器/Node 实现细节（是否继承
  Error）不可依赖，用 name 判断最稳；
- **Response body 单次消费**：测试 mock 里返回共享 Response 对象
  是隐蔽陷阱。

## Next milestone

0006 — Reader：在 Web Shell 上实现真实阅读
（`GET /api/v1/entries/{entryRef}` 详情 + PATCH 状态操作 UI +
optimistic update + 阅读体验）。Spec 未写，按 PRD §10 流程开工。
