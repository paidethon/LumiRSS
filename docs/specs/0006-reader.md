# Spec 0006 — Reader

> Status: **待人工审核**。批准前不安装依赖、不修改任何实现代码。
> 本文件是批准前唯一允许写入的文件。

## Goal

把 0005 的右侧占位栏变成真正的阅读区：

```text
selectedEntryRef（Zustand UI state）
↓
TanStack Query useEntryDetail（["entry", entryRef]，enabled）
↓
GET /api/v1/entries/{entryRef}
↓
DOMPurify sanitize（唯一安全边界）
↓
ArticleContent 渲染
↓
显式 已读/未读、收藏/取消收藏 按钮（useMutation + PATCH state）
↓
invalidate Detail + Entries → FreshRSS 真实状态回流
```

最终用户可以：点击文章 → 右栏 Loading → 真实读取 Detail →
标题/来源/作者/时间 → 安全显示正文 → 打开原文 → 显式改状态 →
列表与 Reader 重新同步。

## 前置事实核对（Spec 阶段从当前源码真实确认，不是从旧聊天回忆）

### 分支基线（已与用户确认处理）

- `feat/0006-reader` 原本基于 0004（缺 0005），经用户授权已
  fast-forward 合并 `main`（含 PR #11 / 0005 Web Shell，commit `ba95a0c`）。
- 工作区干净；分支上领先 origin 2 个提交（0005 的内容），不 push。

### BFF 当前真实 Contract（读自 `services/bff/src/lumirss/`）

`GET /api/v1/entries/{entryRef}` 目前返回
（[models.py](../../services/bff/src/lumirss/models.py) `EntryDetail`）：

```json
{
  "entryRef": "e1.…",
  "title": "…",
  "feedTitle": "…",
  "author": null,
  "url": null,
  "publishedAt": "2026-08-28T10:00:00Z",
  "read": false,
  "starred": false,
  "contentText": "纯文本正文"
}
```

- **没有 `contentHtml`**。adapter `_content_html_of()` 已拿到 FreshRSS
  原始 `summary.content` HTML（缺失时为 `""`），但只用于生成
  `contentText`，从不外发。
- `GET /api/v1/entries`（列表）永远不含任何正文字段
  （`EntryListItem` 无 content 字段）。
- 错误映射（[main.py](../../services/bff/src/lumirss/main.py)）：
  无效 entryRef → 400 `invalid_entry_reference`；FreshRSS 无此条目 →
  404 `entry_not_found`；均**先于**任何 FreshRSS 调用/或由空 items 判定。
- `PATCH /api/v1/entries/{entryRef}/state`：set 语义（非 toggle），
  strict bool，body `{"read": true}` / `{"starred": false}`（至少一个），
  成功 204 无响应体。

### Web 当前真实结构（读自 `apps/web/src/`）

- [client.ts](../../apps/web/src/api/client.ts)：`request<T>()` 只处理
  JSON 响应（**204 需要新增处理路径**）；`ApiError` 安全错误体系；
  AbortError 原样上抛不包装。公共函数：`getFeeds` / `getEntries`。
- [types.ts](../../apps/web/src/api/types.ts)：`EntryListItem` /
  `EntryListResponse` / `Feed` / `EntryView` / `ApiErrorResponse`。
- [queries.ts](../../apps/web/src/api/queries.ts)：`useFeeds()`（key
  `['feeds']`）、`useEntries(view, feedUrl)`（infinite，key
  `['entries', { view, feedUrl }]`）。
- [reader-ui.ts](../../apps/web/src/store/reader-ui.ts)：Zustand 只有
  `view` / `selectedFeedUrl` / `selectedEntryRef`；`selectView` /
  `selectFeed` 已清空 selection（0006 必须保持，不改动）。
- [App.tsx](../../apps/web/src/App.tsx)：三栏 grid，第三栏当前渲染
  `ReaderPlaceholder`。
- 测试：`__tests__/client.test.ts`、`reader-ui.test.ts`、`shell.test.tsx`；
  vitest + jsdom + RTL，`vi.stubGlobal('fetch', …)` 模式。

## Context — 两个产品级边界（写给初学者）

### 1. 安全边界：为什么 BFF 返回的 HTML 仍然不可信

FreshRSS 的文章正文来自**外部网站的 RSS feed**，任何第三方都可以
发布 feed。正文里可能藏着 `<script>`、`<img onerror=…>`、
`<a href="javascript:…">`。浏览器把 HTML 字符串放进 DOM 时，这些
代码就会执行（XSS 攻击）。

"HTML 是我自己的 BFF 发回来的" 不能改变它的来源：BFF 只是搬运工，
它不懂 HTML 安不安全。所以规则是：

```text
raw contentHtml（不可信）
↓
DOMPurify.sanitize()（唯一清洗点）
↓
sanitizedHtml（已针对 ArticleContent HTML sink 清洗）
↓
ArticleContent 用 dangerouslySetInnerHTML 渲染（全应用唯一例外）
```

同样地，**`EntryDetail.url`（原文链接）也来自外部 RSS，是 untrusted
input**：RSS feed 可以把 `<link>` 写成 `javascript:…` 或相对 URL。React
渲染 `<a href={value}>` 时不会替你拦截这些协议，所以「打开原文」链接
也必须先过一道最小的 URL 安全检查（见 safeExternalHttpUrl）。

DOMPurify 是专门为"不可信 HTML → 安全 DOM"场景设计的库，默认就移除
script / 事件属性 / javascript: 协议，还能限制为纯 HTML profile（不允许
SVG / MathML 命名空间）。

### 2. 读取/修改边界：useQuery vs useMutation

- **读取**（Detail）：`useQuery`，key `["entry", entryRef]`。换选择 =
  换 key，TanStack Query 自动取消旧请求（复用 client 的 AbortSignal
  透传），天然解决快速切换 A→B 的竞态。
- **修改**（read/starred）：`useMutation` → PATCH → 成功后
  `invalidateQueries` 让 Detail 和所有 Entries 重新从 FreshRSS 拉取
  真实状态。**不做 optimistic update**（见下）。

### 为什么不做 optimistic update

Optimistic update = 点击后立刻把 UI 改成"假设成功"的样子，等服务器
确认，失败再回滚。它需要手工改缓存 + 回滚上下文，出错面大。0006 数据
量很小（单篇文章、本地网络），多等一次请求换实现简单 + 永远显示
FreshRSS 真实状态，是正确取舍。以后有性能需求再单独评估。

### 为什么不自动标记已读

打开文章**没有隐藏写操作**。只有用户点"标记为已读"按钮才 PATCH。
行为可理解、无隐藏副作用、不会出现"只是点开却改了状态"、也不需要处理
React StrictMode 双 effect。以后可单独评估"打开自动已读"的 UX。

## Scope（只做四类能力 + 必要的最小 BFF Contract 扩展）

1. **Entry Detail Query**：`getEntry` client 函数 + `useEntryDetail`。
2. **Safe Article Rendering**：BFF `contentHtml` 最小扩展 +
   `sanitize-article-html` + `ArticleContent`（HTML / 纯文本 fallback /
   空正文三种路径）。
3. **Read / Star Mutation UI**：`setEntryState` client 函数 +
   `useEntryStateMutation` + Reader header 两个显式按钮。
4. **Reader loading / error / empty / 404 states**。

## Non-goals（明确不做，做了就是 scope creep）

Mobile 布局、PWA、Offline、Service Worker、React Router、URL permalink、
键盘快捷键、手势、可拖拽分栏、主题/暗色模式、字体设置、Reader 偏好、
Category、Search、Feed CRUD、OPML、Mark all read、批量状态、全文抓取
（Trafilatura / Readability / 原始页面 fetch）、图片代理、AI 摘要、翻译、
RSSHub、Caddy、ECS、SQLite、Redis、后台任务、optimistic update 框架、
auto mark-read、link rewriting / 事件委托路由、scroll restoration 框架、
`@tailwindcss/typography`。

## 依赖变更（唯一新增 runtime 依赖，批准后才安装）

| 包 | 版本 | 用途 |
|---|---|---|
| `dompurify` | `^3.4.14`（npm registry dist-tags.latest，本 Spec 阶段实际查询确认） | 渲染不可信 RSS HTML 前清洗 |

- License：Apache-2.0 / MPL-2.0 双许可；零 runtime 依赖；
  **自带 TypeScript 类型**（不需要 `@types/dompurify`）。
- 只在 `src/lib/sanitize-article-html.ts` 一处调用。
- 不引入第二个 sanitizer；不手写 regex sanitizer / 字符串替换 / XSS
  黑名单；不引入 `html-react-parser` / `sanitize-html` /
  `isomorphic-dompurify` / `react-markdown` / `marked` / rehype /
  remark / icon / date / router / axios / zod / UI / animation 库。
- 安装命令：`cd apps/web && pnpm add dompurify`（不混用 npm/yarn/bun）。

## BFF Contract 变更（冻结）

### EntryDetail 新增 `contentHtml`

```json
{
  "entryRef": "e1.…",
  "title": "Article",
  "feedTitle": "Feed",
  "author": null,
  "url": "https://example.com/article",
  "publishedAt": "2026-08-28T10:00:00Z",
  "read": false,
  "starred": false,
  "contentText": "fallback plain text",
  "contentHtml": "<p>Article <strong>content</strong></p>"
}
```

规则：

- `contentHtml: string | null`。上游 `summary.content` 缺失或为空字符串
  → `null`（Spec 冻结：空字符串一律归一化为 `null`，前端只判 null）。
- **只出现在 Detail**。`list_entries()` 与 `EntryListItem` 不动。
- 来源仅为 FreshRSS 当前保存的 Entry HTML；不抓原始网站。
- `contentText` 继续保留并继续由 HTML 生成（fallback 路径不变）。
- BFF **不做任何 sanitize**——它只 transport untrusted HTML；sanitize 是
  Web rendering boundary 的事（代码注释必须写明
  "contentHtml is untrusted upstream HTML"）。
- 不改 Auth Token / Action Token 生命周期；不改 `.env` / FreshRSS 配置。

### 预计修改文件（BFF，上限）

- `services/bff/src/lumirss/models.py` — `EntryDetail` 加
  `contentHtml: str | None = None`，docstring 更新。
- `services/bff/src/lumirss/adapters/freshrss.py` — `get_entry()` 传入
  `contentHtml=base["content_html"] or None`。
- `services/bff/tests/` 对应测试。
- `main.py` 预计**零改动**（`response_model` 自动序列化新字段；只有
  实际证明必要时才允许极小调整）。

不得新建 Service layer / Repository / backend sanitizer / database /
full-text fetcher。

## Frontend 设计（冻结）

### types.ts 新增

```ts
export interface EntryDetail {
  entryRef: string
  title: string
  feedTitle: string
  author: string | null
  url: string | null
  publishedAt: string | null
  read: boolean
  starred: boolean
  contentText: string
  contentHtml: string | null
}
```

与 BFF 字段一一对应，不加后端不存在的字段（readingTime / wordCount /
summary / favicon / heroImage 等一律禁止）。

### client.ts 新增（公共函数上限：这两个之后不再加）

```ts
export async function getEntry(entryRef: string, signal?: AbortSignal): Promise<EntryDetail>
// GET /api/v1/entries/{encodeURIComponent(entryRef)}
// entryRef 虽然是 URL-safe base64url，仍必须 encodeURIComponent（路径段安全）。
// signal 透传（复用现有 request<T> + AbortError 规则）。

export async function setEntryState(
  entryRef: string,
  patch: { read: boolean } | { starred: boolean },
): Promise<void>
// PATCH /api/v1/entries/{encodeURIComponent(entryRef)}/state
// body: JSON.stringify(patch)；Content-Type: application/json
// 成功 = 204 No Content → 不尝试 response.json()（需要 request 之外
// 一条不解析响应体的路径，复用同一套 ApiError 规则）。
// 注意：**没有 AbortSignal 参数**——Query cancellation 与 Mutation
// 严格区分：GET Detail 用 useQuery 的 AbortSignal（A→B 快速切换可以
// abort A）；PATCH 是写操作，mutation 不建立自定义 AbortController，
// 请求一旦发出允许正常完成，不因切换 Entry / 组件 unmount 主动 abort
// write。不创建 mutation cancellation framework。
```

- 组件**禁止**直接 `fetch(...)`；所有 BFF HTTP 继续集中在 client.ts。
- 前端仍发**目标状态**（set 语义），没有任何 toggle。

### queries.ts 新增

```ts
export function useEntryDetail(entryRef: string | null) {
  return useQuery({
    queryKey: ['entry', entryRef],
    queryFn: ({ signal }) => getEntry(entryRef!, signal),
    enabled: entryRef !== null,   // 无选择时不发请求
  })
}

export function useEntryStateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { entryRef: string; patch: { read: boolean } | { starred: boolean } }) =>
      setEntryState(vars.entryRef, vars.patch),
    onSuccess: async (_data, variables) => {
      // entryRef 来源冻结：必须用“这一次 mutation 的 variables.entryRef”，
      // 禁止读取当前 Zustand selectedEntryRef（mutation 完成前 selection
      // 可能已切到另一篇，读了就会 invalidate 错误的 key）。
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['entry', variables.entryRef] }),
        // Entries 前缀失效：覆盖 all/unread/starred × 全部 feedUrl scope
        queryClient.invalidateQueries({ queryKey: ['entries'] }),
      ])
    },
  })
}
```

（实际实现按当前 TanStack Query v5 类型细节化；`['entries']` 前缀匹配
`['entries', { view, feedUrl }]` 全部 scope。）

- **Query cancellation 与 Mutation 区分（冻结）**：只有 GET Detail 走
  useQuery 的 AbortSignal；PATCH mutation 不建 AbortController、不因
  切换/卸载 abort 写请求。
- Zustand **零改动**：`selectedEntryDetail` / `contentHtml` /
  `contentText` / `read` / `starred` / mutation error 严禁进 Zustand。
- 切 view/feed 清空 selection 的既有行为不动。

### sanitize-article-html.ts（唯一 DOMPurify 调用点）

新文件 `apps/web/src/lib/sanitize-article-html.ts`：

```ts
import DOMPurify from 'dompurify'

// 唯一允许调用 DOMPurify.sanitize() 的位置。
// contentHtml 来自外部 RSS feed，是不可信输入。
export function sanitizeArticleHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },   // 纯 HTML profile：不允许 SVG/MathML
    FORBID_TAGS: ['form', 'input', 'button', 'textarea', 'select',
                  'option', 'iframe', 'object', 'embed', 'style', 'template'],
    FORBID_ATTR: ['style'],          // inline style 一律移除
  })
}
```

- DOMPurify 默认已移除 `<script>`、`on*` 事件属性、`javascript:` URL
  （含 URI 安全规则）——**不自己写 URI sanitizer regex**。
- sanitize 之后**不再修改字符串**（不做 regex replace / string
  manipulation），避免破坏安全保证。
- 远程 `<img>` 直接由浏览器加载（允许；CSS 限宽）；不做代理/缓存/重写。

### safeExternalHttpUrl（原文链接安全边界，最小纯函数）

新文件 `apps/web/src/lib/safe-external-http-url.ts`（或并入现有结构下
等价位置，不新增依赖）：

```ts
/** EntryDetail.url 来自外部 RSS，是 untrusted input。
 * 只允许绝对 http: / https: URL；其它一律返回 null。 */
export function safeExternalHttpUrl(value: string | null): string | null {
  if (value === null) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null // malformed / relative → null
  }
}
```

规则（冻结）：

- 只允许绝对 `http:` / `https:`（含 `URL` 能解析的 malformed → null，
  `javascript:` / `data:` / `file:` / 相对 URL → null）。
- **不**用当前 LumiRSS origin 自动补全相对 URL。
- 不新增依赖，不建 URL sanitizer 框架——就这一个纯函数。
- 正文内 sanitized `<a>` 不在本任务额外 rewrite，仍由 DOMPurify URI
  policy 处理；本函数只服务 ReaderHeader 的「打开原文」按钮。

### 组件（最多 3 个新文件）

```text
apps/web/src/
├── api/        client.ts / types.ts / queries.ts（修改）
├── lib/        sanitize-article-html.ts / safe-external-http-url.ts（新增）
└── components/ Reader.tsx / ReaderHeader.tsx / ArticleContent.tsx（新增）
```

不创建 `reader/` / `features/` / `domain/` / `services/` /
`repositories/` / `mutations/` 目录。

#### Reader.tsx（状态机，挂在 App 第三栏）

```text
selectedEntryRef == null        → <ReaderPlaceholder />（保留既有空状态文案）
query.isPending                 → Reader skeleton（title/meta/正文几行占位）
query.isError && status == 404  → 「这篇文章已经不存在或不可用了。」+ 返回文章列表按钮
                                  （selectEntry(null)，不 reload 页面）
query.isError（其它）           → 「文章加载失败」+ 安全 error.message + 重试按钮
success                         → <ReaderHeader detail/> + <ArticleContent detail/>
```

- Sidebar / EntryList 在 Reader 任何状态下照常工作，绝不白屏。
- 容器 `overflow-y-auto`；`selectedEntryRef` 变化时用最小
  ref + effect 把 Reader 滚回顶部（不做 scroll restoration 框架）。
- 404 判定：`ApiError.status === 404`（BFF `entry_not_found`）。
- Entry 因状态修改从当前列表消失时：Reader **继续显示**该 Detail，
  不报错、不自动选下一篇、不自动关闭。

#### ReaderHeader.tsx

- 显示：`title`、`feedTitle`、`author`（如有）、`publishedAt`（如有，
  继续用 `Intl.DateTimeFormat`，不引入 date library）。
- `safeExternalHttpUrl(detail.url)` 非 null 才渲染「打开原文」
  `<a target="_blank" rel="noopener noreferrer">`；返回 null（包括
  `detail.url == null`、javascript:/data:/file:/相对/malformed）→ 整个
  按钮不渲染（禁止直接 `<a href={detail.url}>`，禁止根据 feed URL 猜
  文章 URL）。
- **防跨 Entry 泄漏（冻结方案：React key）**：Reader 内渲染 ReaderHeader
  时以 `detail.entryRef` 作为 React `key`（`<ReaderHeader key={detail.entryRef} …>`）。
  切换 Entry = key 变化 = 组件重挂载，旧 mutation 的 pending / error UI
  天然不残留到新 Entry，不增加状态管理层，也不需要 mutation.reset。
- 两个显式状态按钮（`<button>`），共用**同一个** `useEntryStateMutation`
  实例（不为 read/star 各建一套 hook）：

```text
read=false    → 「标记为已读」   → patch { read: true }
read=true     → 「标记为未读」   → patch { read: false }
starred=false → 「收藏」         → patch { starred: true }
starred=true  → 「取消收藏」     → patch { starred: false }
```

- **并发简化（冻结）**：任意一个 Entry state mutation pending 时，
  read/unread 与 star/unstar **两个按钮都 disabled**——同一篇 Entry 同时
  最多一个状态 PATCH in-flight（一个 mutation 实例天然如此），按钮文案
  可显示轻量「处理中…」（无 icon 库）。
- Mutation error：Reader header 区域显示「状态更新失败」+ 安全
  `ApiError.message`；不清空文章、不崩溃、不显示 stack trace；因为没有
  optimistic update，缓存里的旧状态自然保留（不伪造成功）。
- Accessibility：状态按钮用 `aria-pressed` 表达当前 read/starred UI
  状态（API 仍是 set 语义）。

#### ArticleContent.tsx（dangerouslySetInnerHTML 全应用唯一例外）

```text
contentHtml != null && contentHtml.trim() !== ""
  → sanitizeArticleHtml(contentHtml) → dangerouslySetInnerHTML
contentHtml == null / 空白
  → contentText（React 正常文本渲染 + white-space: pre-wrap，不包装成 HTML）
两者都空
  → 「这篇文章没有可显示的正文。」（不是 Error）
```

### 样式（index.css 追加 `.article-content` 普通 CSS）

- Tailwind 已有 + 极少量普通 CSS 覆盖：`p, h1–h6, strong, em, a,
  blockquote, ul, ol, li, pre, code, img, figure, figcaption, table, th,
  td, hr`。
- 舒适行高（~1.7）、合理段落间距、`pre/code` 横向滚动、
  `img { max-width: 100%; height: auto; }`、表格必要时横向滚。
- Reader 内容 `max-width: ~44rem（700px 级）` + `margin-inline: auto`，
  避免超宽屏一行横跨 1000+px。
- 视觉延续 0005：clean / calm / reading-first / light / neutral；
  不做完整 Design System、不做 floating toolbar / 动画 / dropdown。
- 可选轻量 sticky header，非必须。

### Mutation 成功后的同步（冻结）

PATCH 204 → invalidate `["entry", entryRef]`（精确；entryRef 取自本次
mutation 的 `variables.entryRef`，禁止读当前 Zustand
selectedEntryRef）+ `["entries"]`（前缀，覆盖 all/unread/starred × 全部
feed scope，`Promise.all` 并行）→ UI 显示 FreshRSS 真实回流状态。
onSuccess 可等待 invalidation Promise。不刷新整个页面。

预期副作用（合法行为，写测试外的行为说明）：view=unread 时标记已读
→ refetch 后该条从未读列表消失；view=starred 时取消收藏同理。Reader
继续显示已选文章，不自动导航。

## Testing strategy（自动测试：无真实网络、无真实 Secret）

沿用 0005 模式：vitest + jsdom + RTL + `vi.stubGlobal('fetch', …)`；
BFF 用既有 Fake FreshRSS mock 模式。**不要求固定测试数量，数量由行为
自然决定。**

### BFF 测试

- **A — Detail contentHtml mapping**：Fake FreshRSS 返回
  `<p>Hello <strong>Reader</strong></p>` → Detail `contentHtml` 原样返回。
- **B — no HTML**：上游正文缺失/空字符串 → `contentHtml === null`。
- **C — List regression**：`GET /api/v1/entries` 响应体不含
  `contentHtml` / `contentText`。
- **D — Existing regression**：0002–0004 全部 backend 测试无回归
  （当前基线 120 passed）。

### Web client 测试

- **E — getEntry**：请求路径
  `/api/v1/entries/{encodeURIComponent(entryRef)}`（用含需转义字符的
  ref 验证编码）；AbortSignal 透传；AbortError 不包装。
- **F — setEntryState**：`{read:true}` / `{read:false}` /
  `{starred:true}` / `{starred:false}` 四种 → PATCH + JSON body +
  `Content-Type: application/json`；204 成功且**不调用** `response.json()`。
- **G — errors**：Detail / PATCH 的 4xx / 5xx / network → ApiError 体系；
  AbortError 原样上抛（仅适用于带 signal 的 getEntry；setEntryState
  无 signal，不涉及）。

### Sanitizer 安全测试（0006 最重要的安全测试）

输入：

```html
<p>Hello <strong>LumiRSS</strong></p>
<script>alert(1)</script>
<img src="x" onerror="alert(2)">
<a href="javascript:alert(3)">bad</a>
<form><input><button>…</button></form>  <iframe>…</iframe>  <style>…</style>
```

断言（对 sanitize 输出的 DOM 结构，不测"脚本有没有执行"）：

- `p` / `strong`（含内容）保留；
- `script` 不存在；`onerror` 属性不存在；`javascript:` href 不存在；
- `form` / `input` / `button` / `iframe` / `style`（按最终 FORBID 配置）
  被移除。

### Reader 组件测试

- **H — no selection**：`selectedEntryRef = null` → 显示 Placeholder，
  fetch 未被调用。
- **I — loading**：Detail pending → loading skeleton。
- **J — success HTML**：`contentHtml` 有值 → title/feed/meta + sanitized
  富文本正确显示。
- **K — text fallback**：`contentHtml = null`、`contentText != ""` →
  纯文本显示。
- **L — empty body**：两者皆空 → 「这篇文章没有可显示的正文。」非 Error。
- **M — detail error**：非 404 失败 → 「文章加载失败」+ 重试；Shell 不崩。
- **N — 404**：ApiError(404) → unavailable 文案 + 返回列表按钮。
- **Original link（safeExternalHttpUrl）**：`https://` / `http://` 的
  `url` → 「打开原文」存在且 `target="_blank"`、`rel` 含
  `noopener noreferrer`；`url` 为 `javascript:` / `data:` / `file:` /
  相对 URL / malformed / null → 按钮不存在。（纯函数本身与 ReaderHeader
  分别测试：https/http → link exists；javascript/data/file/relative/
  malformed → null → link absent。）
- **Read mutation**：read=false 点「标记为已读」→ PATCH body
  `{"read": true}`；read=true 点「标记为未读」→ `{"read": false}`；
  禁止 toggle。
- **Star mutation**：同理 `{starred: true}` / `{starred: false}`。
- **Cache invalidation**：PATCH 成功 204 后 `["entry", entryRef]` 与
  `["entries"]` 前缀被 invalidate（不要求 optimistic cache mutation）。
- **Mutation invalidation race**：对 Entry A 发 mutation，在其完成前
  selection 切到 Entry B；A mutation 成功后 → 精确 invalidate
  `["entry", A]`，**不得**错误 invalidate `["entry", B]`；`["entries"]`
  prefix 同时 invalidated。
- **Mutation error**：PATCH 失败 → 文章仍显示、状态不本地伪造、显示
  安全错误。
- **Mutation pending**：任一状态 mutation pending → read/unread 与
  star/unstar **两个按钮均 disabled**（同一 mutation 实例）。
- **跨 Entry 泄漏**：Entry A 的 mutation 失败后切到 Entry B → 旧 error
  UI 不残留（由 `key={detail.entryRef}` 重挂载保证，测试复现）。
- **Selection race**：A→B 快速切换，最终显示 B（由 queryKey + signal
  保证，用测试复现）。
- **0005 regression**：Sidebar / Views / Feeds / Entry List / Load More /
  Selection 既有测试全部继续通过，不为 Reader 重写 Web Shell。

## Acceptance Criteria（AC1–AC28）

| # | 标准 |
|---|---|
| AC1 | 所有修改在 `feat/0006-reader` |
| AC2 | 0005 前端 + 0004 后端 baseline 在改动前健康 |
| AC3 | 选择 Entry 后 `GET /api/v1/entries/{entryRef}` 真实工作 |
| AC4 | Detail query key `["entry", entryRef]`；无 selection 不请求 |
| AC5 | Detail/mutation state 不进 Zustand |
| AC6 | BFF Detail 最小增加 `contentHtml`；List 不增加任何正文 |
| AC7 | 所有 untrusted RSS HTML 渲染前必经 DOMPurify |
| AC8 | 自动测试证明 script / 事件属性 / javascript: URL / iframe / form / style 移除 |
| AC9 | `dangerouslySetInnerHTML` 只存在于 ArticleContent sanitized 边界 |
| AC10 | 无 HTML 时 `contentText` 纯文本可读 |
| AC11 | 无可用内容显示 empty body UI，不报错 |
| AC12 | Reader 正确处理 no selection / loading / success / 404 / error |
| AC13 | 原文 `url` 经 safeExternalHttpUrl（仅绝对 http/https）后才渲染「打开原文」，安全新标签打开（noopener noreferrer） |
| AC14 | read true/false 均能从 Web UI 同步到 FreshRSS |
| AC15 | starred true/false 均能同步 |
| AC16 | 前端发目标状态（set 语义），无 toggle API |
| AC17 | PATCH 成功后 Detail + Entries queries 正确 invalidated/refetched，entryRef 取自 mutation `variables.entryRef`（非当前 selection） |
| AC18 | 无手写 optimistic rollback / normalized cache layer |
| AC19 | 写失败不伪造成功、不清空 Reader、显示安全错误 |
| AC20 | 打开文章不自动改变 read state |
| AC21 | 真实 read/star smoke 后最终状态 == 原状态（恢复失败即 FAIL） |
| AC22 | 全部 Web 自动测试实际全绿（报告真实数字） |
| AC23 | 全部 Backend 自动测试无回归（报告真实数字） |
| AC24 | `pnpm lint` / `pnpm build` 真实通过 |
| AC25 | Browser → React → /api → BFF → FreshRSS → Detail 真实链路成功 |
| AC26 | 1440 / 1280 / 1024 Reader 可用，无重大 overflow，行长合理；视觉不可用则诚实标 UNVERIFIED |
| AC27 | 除 dompurify 外无新增业务依赖 |
| AC28 | 无 Mobile/PWA/Router/auto mark read/Full-text/AI/RSSHub/Caddy/Category/Search/Settings 越界实现 |

## Tasks（批准后严格逐步执行，每步完成即验证）

1. Baseline check：`node --version` / `pnpm --version`；
   `cd apps/web && pnpm test && pnpm lint && pnpm build`；
   `cd services/bff && uv run pytest`。基线失败 → 停止报告。
2. BFF：`EntryDetail.contentHtml`（models.py + adapter `get_entry`）。
3. BFF tests A/B/C + 全量回归（D）。
4. Frontend types.ts：`EntryDetail`。
5. client.ts：`getEntry` + Test E。
6. client.ts：`setEntryState`（204 路径）+ Test F/G。
7. queries.ts：`useEntryDetail`（enabled）+ 测试（H 含无请求断言）。
8. `pnpm add dompurify`。
9. `sanitize-article-html.ts` + sanitizer 安全测试。
10. `safe-external-http-url.ts` 纯函数 + 测试（https/http → 通过；
    javascript/data/file/relative/malformed → null）。
11. Reader.tsx：loading / error / 404 状态机 + 测试 I/M/N。
12. ReaderHeader.tsx（title/meta/原文链接，`key={detail.entryRef}`
    防跨 Entry 泄漏）+ 测试 J（含原文链接断言）。
13. ArticleContent.tsx：HTML / text fallback / empty + 测试 J/K/L。
14. `useEntryStateMutation`（无 AbortController；onSuccess 用
    `variables.entryRef`）+ invalidation + 测试（Read/Star mutation、
    invalidation、invalidation race、mutation error、两按钮并发 disabled、
    跨 Entry 泄漏）。
15. App.tsx 接入 Reader；selection race 测试。
16. `.article-content` CSS + Reader 滚回顶部 effect。
17. 全量 `pnpm test` + `pnpm lint` + `pnpm build`。
18. 全量 `uv run pytest`。
19. Real smoke — Detail：起 FreshRSS + BFF + Vite，点一篇真实 Entry，
    Network 确认 `GET /api/v1/entries/<entryRef>` → 200；Reader 显示
    title / feedTitle / author·time（如有）/ 正文（只记录 non-empty，
    不复制正文）。富 HTML 样本：真实存在则验证段落/链接/图片；13 篇都
    没有 → 如实记 "Live rich HTML sample unavailable"，由 sanitizer
    tests 覆盖安全路径；**不篡改 FreshRSS 数据造样本**。
20. Real smoke — Read（可恢复）：记录 original_read（仅 bool）→ 点按钮
    → PATCH → 重新 GET 确认真实更新 → 恢复 → final_read == original_read。
21. Real smoke — Starred：同上。恢复失败 → 立即停止并报告，不得宣称 PASS。
22. （顺带观察即可，不为 smoke 额外改更多真实 Entry：Unread view 标记
    已读后条目从列表消失。）
23. 视觉检查 1440 / 1280 / 1024。
24. 安全复查：`grep dangerouslySetInnerHTML` 只有 ArticleContent 一处；
    「打开原文」href 必经 safeExternalHttpUrl（禁止直接
    `href={detail.url}`）；待提交代码无 FRESHRSS_* / token /
    Authorization / .env 内容（测试 fixture 中的 `<script>alert(…)` 属
    sanitizer 安全 fixture，不误报）。
25. 依赖审计：新增 direct runtime 仅 dompurify。
26. 文档：README / PROJECT_STATE / board（0006 completed、0007 next、
    Phase 3 仍 current）/ devlog 0006。
27. Final verification：全部命令真实跑 + `git branch --show-current` /
    `git status` / `git diff --stat` / `git diff --check` / `git diff`。
    不 commit、不 push、不建 PR，停在工作区等待人工 Review。

## Verification

```bash
cd apps/web && pnpm test && pnpm lint && pnpm build
cd ../../services/bff && uv run pytest
git branch --show-current        # feat/0006-reader
git status --short --branch      # 只含任务范围内文件
git diff --check                 # 无空白错误
grep -rn "dangerouslySetInnerHTML" apps/web/src   # 仅 ArticleContent
```

## Error 处理原则（遇到问题时）

先定位层：FreshRSS entry data → BFF mapping → API Contract → fetch →
TanStack Query → mutation → DOMPurify → React rendering → CSS → tests。
报告：现象 → 证据 → 问题层 → 原因 → 最小修复。正文样式问题绝不动
FreshRSS / 不加 scraper / markdown / database / 不重写 Adapter。

## Documentation updates（AC 全过后单独做）

- README：只写实际存在的 Reader detail / safe HTML rendering /
  read·star UI 与真实跑通的命令；不写 PWA / Mobile / AI / Full-text /
  Production。
- PROJECT_STATE：Implemented 增加 Entry Detail Reader、Safe RSS HTML
  rendering、contentText fallback、Original article link、Read/unread UI、
  Star/unstar UI、TanStack mutation synchronization；Current →
  Phase 3 — Reading Experience；Next → 0007 — Mobile + PWA。
- Board：0006 → completed，0007 → next，Phase 3 仍 current。
- Devlog `docs/devlog/0006-reader.md`：Status / Goal / Reader
  architecture / Entry Detail contract / contentHtml trust boundary /
  DOMPurify design（为何必须 sanitizer）/ Mutation design（为何不用
  optimistic update）/ Tests / Real smoke / 状态恢复 / Visual review /
  Problems / Solutions / What I learned / Next。禁止记录完整文章正文、
  Secret、Token、Authorization Header、AI internal reasoning。

## Risks / Unknowns

- **远程图片隐私**：真实 feed 的 `<img>` 由浏览器直接加载，会暴露
  读者 IP 给图片服务器。这是当前简单 Reader 的已知行为；图片隐私代理
  不属于 0006（PRD 后续处理），此处明确记录。
- **Live 富 HTML 样本可能不存在**：当前 FreshRSS 只有约 13 篇真实文章，
  可能全是纯文本。应对：换一篇再试；仍无则如实记录并由 sanitizer
  自动测试覆盖安全路径，不篡改数据。
- **jsdom 与 DOMPurify**：dompurify v3 默认导出在 jsdom 环境自动绑定
  window，测试可直接用；若行为异常，问题定位在测试环境层，不改
  sanitizer 设计。
- **entryRef 路径编码**：`e1.` + base64url 本身 URL-safe，但 client 仍
  统一 `encodeURIComponent` 防御（浏览器/代理对 `.`、`-`、`_` 的差异）。
- **204 解析**：现有 `request<T>` 无条件 `response.json()`；PATCH 需要
  一条不解析响应体的路径，这是 client 内部结构的最小调整，不影响既有
  两个读函数。
