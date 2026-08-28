# Spec 0007 — Mobile + PWA

> 日期：2026-08-28
> 对应 PRD 阶段：Phase 3 — Reading Experience（第三个里程碑，收官）
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**
> 批准前唯一允许写入的文件是本 Spec。

## Goal

让同一套 LumiRSS Web 应用同时适合 Desktop / Tablet / Phone，并提供
基础 PWA 可安装能力：

```text
<1024px（Phone / Tablet）
  Mobile Header（☰ / ← 返回）
      ├─ Drawer（打开后是同一份 Sidebar 内容）
      └─ Main（单主内容区）
           ├─ selectedEntryRef == null → Entry List
           └─ selectedEntryRef != null → Reader（全屏替换列表）

≥1024px（Desktop）
  保持 0005/0006 已有三栏：Sidebar | Entry List | Reader

PWA（无 Service Worker）
  index.html
    ↓ link[rel=manifest]
  manifest.webmanifest（name / start_url / standalone / icons）
    ├─ 192×192 PNG
    ├─ 512×512 PNG
    ├─ 512×512 maskable PNG
    └─ 180×180 apple-touch-icon
```

0007 不重新设计任何业务功能。它只回答两个问题：

1. **手机上能不能真正舒服地使用 LumiRSS？**
2. **能不能以 PWA 形式安装到桌面 / 主屏幕？**

## 前置事实核对（Spec 阶段从当前源码与本机环境真实确认，不是从旧聊天回忆）

### 分支基线（已验证）

```text
git branch --show-current   → feat/0007-mobile-pwa
git status --short --branch → 干净（无未提交改动）
git log                     → 基于 main（1e12175，含 PR #12 / 0006 Reader）
```

### 0006 前置已满足

0006 — Reader 已经 Review → Commit → PR #12 → Merge into main：
Entry Detail、DOMPurify 安全渲染、contentText fallback、原文链接、
Read/Unread、Star/Unstar 全部在位（`Reader.tsx` / `ReaderHeader.tsx` /
`ArticleContent.tsx` / `queries.ts` / `reader-ui.ts` 均已读实）。

### 当前 Web 代码事实（逐文件读自 `apps/web/src/`）

- **[App.tsx](../../apps/web/src/App.tsx)**：无条件三栏
  `grid h-dvh grid-cols-[240px_400px_1fr] max-[1100px]:grid-cols-[220px_360px_1fr]`。
  **没有任何 <1024px 的响应式处理**——390px 下三栏硬挤（这正是 0007
  要解决的核心问题）。三栏各自 `overflow-y-auto`，`h-dvh` 已在用。
- **[index.html](../../apps/web/index.html)**：viewport 为
  `width=device-width, initial-scale=1.0`——**没有 `viewport-fit=cover`**；
  无 manifest link、无 theme-color、无 apple-touch-icon。
- **[index.css](../../apps/web/index.css)**：已有 CSS variables
  `--bg:#f5f5f4 / --surface:#ffffff / --border:#e5e7eb / --accent:#2563eb /
  --text / --text-muted`；`.article-content` 已含
  `img{max-width:100%}`、`pre{overflow-x:auto}`、
  `table{display:block;overflow-x:auto}`、`word-break:break-word`——
  正文 overflow 防护基础已存在，0007 只需查漏补缺（如 `a` 长链接
  的 `overflow-wrap` 已由 word-break 覆盖，Build 时复核）。
- **[Reader.tsx](../../apps/web/src/components/Reader.tsx)**：成功态
  `article` 为 `mx-auto max-w-[44rem] px-8 py-6`——手机上左右 32px
  padding 偏大（目标 16–20px）；`max-w-[44rem]` 配合 `mx-auto` 在窄屏
  不会造成 overflow（max-width 只在宽于 704px 时生效），保留。
- **[ReaderHeader.tsx](../../apps/web/src/components/ReaderHeader.tsx)**：
  状态按钮 `px-3 py-1`（约 30px 高）——不满足 44px touch target；
  按钮容器已 `flex flex-wrap`（wrap 已天然支持）。
- **[EntryRow.tsx](../../apps/web/src/components/EntryRow.tsx)**：标题
  `truncate` 单行截断——手机上必须允许 wrap；metadata 行
  `feedTitle · author · publishedAt`，author 已条件渲染（缺失不占空间）。
- **[EntryList.tsx](../../apps/web/src/components/EntryList.tsx)**：列表
  内部滚动 + footer Load More（`px-3 py-1.5`，需 touch target 复核）；
  header 显示 scope 标题 + 已加载条数。
- **[Sidebar.tsx](../../apps/web/src/components/Sidebar.tsx)**：NavButton
  `px-3 py-1.5`（约 30px 高，需 mobile touch target 调整）；feeds
  loading/error 态齐全。
- **[reader-ui.ts](../../apps/web/src/store/reader-ui.ts)**：Zustand 只有
  `view / selectedFeedUrl / selectedEntryRef`；`selectView` / `selectFeed`
  已清空 `selectedEntryRef`（幂等，同值 no-op）——0007 必须保持不动。
- **[queries.ts](../../apps/web/src/api/queries.ts)**：`useFeeds` /
  `useEntries`（infinite）/ `useEntryDetail`（enabled）/ 
  `useEntryStateMutation`（invalidate `["entry", ref]` + `["entries"]`
  前缀）。0007 零改动。
- **[public/](../../apps/web/public/)**：只有 `favicon.svg`（48×46 紫色
  光流图形，#863bff/#7e14ff/#47bfff——仓库中唯一已存在的品牌视觉资产，
  0007 复用它作为 PWA 图标源）。**没有** manifest、没有 icons 目录、
  没有任何 PNG。
- **技术栈**：Tailwind CSS v4（`@tailwindcss/vite`，`lg` breakpoint =
  1024px）、Vitest + jsdom + RTL、oxlint；测试基线 **97 个 Web 测试**
  全绿。

### 本机工具事实（Icon 生成方案的关键输入，已逐一实测）

```text
ImageMagick (convert/magick/identify)  → 不存在
Inkscape                                → 不存在
rsvg-convert                            → 不存在
chromium / google-chrome CLI            → 不存在
Python PIL / cairosvg                   → 不存在
file                                    → 存在（/usr/bin/file，可验证 PNG 尺寸）
```

另外：0006 devlog 记录过「Playwright Chromium 184MB 下载被网络阻断」。
当前 Qoder 环境提供托管的 browser-use / playwright MCP 浏览器工具
（是否可用需 Build 时实测）。**结论：本机没有任何传统 CLI rasterizer，
SVG → PNG 必须依赖环境内已有的浏览器工具，详见 PWA Icons 一节。**

### BFF

`services/bff` 与 0007 完全无关：Mobile/PWA 是纯 Web 层话题。预期
**BFF 零代码修改**，仅跑回归（当前基线 121 tests）。

## Context — 概念解释（写给初学者）

### Responsive Design：为什么不是"再写一份手机版 React"

最直觉的错误做法是 `const isMobile = ...; return isMobile ? <MobileApp/> : <DesktopApp/>`
——复制一整套组件。后果：每个 bug 修两遍，业务逻辑悄悄分叉，
列表状态、Reader 安全边界都要维护两份。

正确做法是**同一棵组件树，CSS 决定布局**：组件只写一次，浏览器根据
视口宽度应用不同样式。React 结构层面只新增两个真正属于"手机交互"
的小组件（MobileHeader、MobileNavigationDrawer），Sidebar / EntryList /
Reader / ReaderHeader / ArticleContent 全部复用。

### Breakpoint：为什么是 1024px

Tailwind 内置 `lg` = 1024px。1024px 恰好是"还能舒服放下
240+400+剩余"的最小桌面宽度；低于它的 iPad 竖屏 / 手机若继续三栏，
Reader 只剩极窄区域（768px 下 240+400=640，Reader 仅剩 128px——
不可用）。沿用 `lg` 避免自造 987px 这类随机值；当前代码里的
`max-[1100px]` 只是 1024–1100 桌面区间的列宽微调，不构成第二个
"布局模式"。

### CSS-first responsive：为什么布局尽量 CSS 决定

JS 判断宽度（`window.innerWidth` / UA sniffing / `useWindowSize`）的
问题：旋转屏幕、分屏、浏览器 DevTools 调宽度时 JS 不会自动重算（要
自己监听 resize），而且 UA 字符串可以伪造、不可维护。CSS media query
（Tailwind 的 `lg:` 前缀）是浏览器原生能力，宽度变化即时生效。
0007 中 JS 只负责真正的交互状态：drawer 开关、entry selection——
这些本来就存在于现有 Zustand/React 状态里。

### Drawer：它和 Desktop Sidebar 的关系

手机上没有 240px 常驻侧栏的空间，但导航内容（All/Unread/Starred/
Feeds）是同一份。所以把**同一个 `<Sidebar />` 组件**放进一个可滑出
的抽屉里：桌面它常驻第一栏，手机它藏在 ☰ 后面。不创建
MobileSidebar——那是复制组件的 scope creep。唯一新增状态是
`mobileSidebarOpen: boolean`（纯 UI 状态）。

### Mobile Reader Flow：为什么 selectedEntryRef 可以直接驱动

0005/0006 已有语义：`selectedEntryRef == null` → 没选文章；
`!= null` → 正在看某篇。这天然就是手机的"列表页 / 阅读页"开关：

```text
selectedEntryRef == null → 手机显示 Entry List
selectedEntryRef != null → 手机显示 Reader（全屏替换列表）
点 ← 返回 → selectEntry(null) → 回到列表（TanStack Query cache 还在，不 reload）
```

不需要再造 `mobilePane = "list" | "reader"`——那是同一信息的第二份
状态，两份状态迟早不同步。而且 0005 已冻结"切 view/feed 清空
selection"：在 Reader 里打开 drawer 换到 Starred，selection 自动清空，
自然回到 Starred 列表——现有语义免费给了我们正确的导航行为。

### Safe Area：为什么 iPhone 需要 env(safe-area-inset-*)

iPhone 的刘海/灵动岛（顶部）和 Home indicator（底部小横条）会压住
普通布局。`viewport-fit=cover` 让网页延伸到整个屏幕后，CSS
`env(safe-area-inset-top/bottom)` 提供"被系统 UI 遮挡了多少像素"，
布局用它留白。Android 全面屏手势条同理。只在少量位置
（Mobile Header 顶、列表 footer 底、Reader 底）用 CSS variables
集中处理，不散落到每个组件。

### 100dvh：为什么比 100vh 更适合手机

手机浏览器地址栏会随滚动收起/展开：`100vh` 是"地址栏展开时"的视口
高度，地址栏收起后 `100vh` 反而比真实视口高——底部内容被裁掉。
`100dvh`（dynamic viewport height）始终等于**当前**视口高度。
当前 App 已用 `h-dvh`，保持。

### Touch target：为什么约 44px 很重要

手指指尖约 40–50px 宽。按钮可视区域只有 24px 时，误触率飙升。
iOS HIG 建议 44×44pt，Android Material 建议 48×48dp——44px 是跨平台
安全下限。做法不是把图标做大，而是给按钮足够的 padding/min-height：
视觉上仍可精致，命中区域必须够大。

### PWA 到底是什么

PWA（Progressive Web App）= 用 Web 技术写的应用，可以**像原生应用
一样被安装**到桌面/主屏幕、以独立窗口（无浏览器地址栏）启动。它由
三样东西支撑：

1. **Web App Manifest**——一个 JSON 文件，告诉浏览器：应用叫什么
   （name）、启动哪个地址（start_url）、以什么模式打开（display:
   standalone）、用什么图标（icons）；
2. **图标**——192/512 PNG 是 Chromium 系安装的最低要求；
3. **Secure Context**——HTTPS（开发时 localhost/127.0.0.1 等价）。

### Standalone 和普通浏览器 tab 的区别

`display: "standalone"` 安装后启动没有浏览器地址栏/标签页，像一个
独立窗口应用；逻辑上和 Browser 模式**完全同一套代码**，不为
standalone 建第二个 App。iOS 上安装走 Safari 分享菜单的
"Add to Home Screen"（不支持 Chromium 风格的 beforeinstallprompt），
Android/Desktop 走浏览器菜单的 "Install app"——都是浏览器原生 UI，
0007 不自建安装按钮。

### Secure Context：为什么 localhost 能开发验证、生产要 HTTPS

浏览器把 `https://` 和 `http://localhost` / `http://127.0.0.1` 都视为
secure context（本机回环不会被中间人篡改）。PWA 安装、及未来可能
的能力（Service Worker、剪贴板等）都要求 secure context。当前 Vite
dev server 跑在 localhost，可直接验证 installability 前置条件；
生产 HTTPS 由后续 Production milestone 的 Caddy 提供（0007 不开始）。

### Service Worker 是什么，为什么 0007 故意不实现

Service Worker 是注册在浏览器里的一个后台脚本，可以拦截/缓存网络
请求——这是很多 PWA 实现**离线体验**的机制。但 MDN 现行文档明确：
Service Worker **不是** PWA 可安装的必要条件；Manifest + secure
context 已提供基础 installability。而 LumiRSS MVP 明确不做完整
Offline，引入 Service Worker 会提前带来旧 HTML shell、过期 Entry、
已读/收藏状态不一致、cache invalidation 等复杂问题。所以 0007：

```text
Manifest / Icons / Standalone / Installability  ✅
Service Worker / 离线缓存 / API cache           ❌
```

### Installability ≠ Offline（必须记住的等式）

```text
可以安装 ≠ 可以离线阅读
```

没有 Service Worker，安装后的 LumiRSS 断网时会正常显示现有的
Query Error UI。README / manifest / 一切文案**不得**出现"离线阅读"
的承诺。

### Maskable Icon：为什么 Android 会裁剪图标

Android 启动器会把图标裁成圆形/圆角方形等各种形状。普通
（purpose: any）图标被裁时可能把细节切掉；maskable 图标的标准
要求：**重要内容位于中央圆形 safe zone——半径为图标宽度的 40%
（即直径 80%）——safe zone 外的外缘可能被平台裁剪**。所以
maskable 版本单独制作：整个 512×512 画布铺满背景色，主体落在
安全区内。LumiRSS 的图标主体目标约 70%（直径）——比标准 80%
更保守，保留不变；不是把普通图标改名。

## Scope（只做七类）

1. **Responsive Mobile Layout**：<1024px 单主内容区 + Mobile Header；
2. **Mobile Navigation**：Menu → Drawer（backdrop/Escape/选择后关闭）；
3. **Mobile Reader Flow**：selectedEntryRef 驱动 list↔reader 切换；
4. **Touch / Safe Area / Mobile UX**：44px touch target、无 hover
   依赖、viewport-fit=cover、safe-area、Entry Row / Reader 手机排版；
5. **Web App Manifest**：静态 `manifest.webmanifest`；
6. **PWA Icons / Metadata**：192/512/maskable/apple-touch 图标 +
   index.html metadata；
7. **Basic Installability Verification**：manifest/icons 可达性 +
   自动化验证 + 真实浏览器 smoke。

## Non-goals（明确不做，做了就是 scope creep）

Offline article reading、offline cache、Service Worker（一切形式）、
Workbox、vite-plugin-pwa、background sync、push notification、
Web Push、notification permission、periodic sync、install reminder
popup、自定义 beforeinstallprompt UI、iOS install tutorial modal、
native wrapper（Capacitor/Tauri/React Native/Expo）、React Router、
permalink routing、deep-link、dark mode、theme settings、Reader
settings、font size settings、gesture library、swipe-to-back、
pull-to-refresh、resizable panes、full offline mode、AI、RSSHub、
Search、Category、Feed CRUD、Caddy、ECS production deployment。

**特别强调：PWA installability ≠ offline support。不因为里程碑名字
里有 PWA 就顺手加入 Service Worker。** 如果 Build 阶段发现当前目标
浏览器的官方安装条件与此理解不一致：停止并报告最新官方依据，
不自行加入 Service Worker。

## 依赖变更

**0 new dependencies（冻结）。**

使用现有：React / Tailwind v4 / Zustand / TanStack Query / DOMPurify /
stdlib browser APIs / Node 内置模块（`node:fs`，仅测试读取 manifest 与
PNG 头）。不引入 vite-plugin-pwa、workbox-*、任何 drawer/gesture/
icon/device-detection/safe-area library。Icon 生成不安装 Sharp/Canvas
等任何依赖（见 Icons 一节）。

## Responsive 架构（冻结）

### Breakpoint 冻结

```text
>= 1024px（Tailwind lg）→ Desktop 三栏（保持 0005/0006 布局）
<  1024px                → Mobile/Tablet：Mobile Header + 单主内容区 + Drawer
```

- 沿用 Tailwind `lg:`，不自造随机 breakpoint；
- 现有 `max-[1100px]:grid-cols-[220px_360px_1fr]`（1024–1100 列宽
  微调）语义上仍属于桌面三栏模式。Build 时以 `lg:max-[1100px]:`
  叠加变体保留；若 Tailwind v4 变体叠加在该场景验证有问题，则退化为
  统一 `240px_400px_1fr`（20–40px 的列宽差异，非布局模式变化），
  在 devlog 记录实际选择。

### App.tsx 布局改造（同一棵组件树，CSS 切换）

概念结构（实际实现按当前代码最小改写）：

```tsx
<div className="flex h-dvh flex-col">
  {/* Mobile Header：<1024 显示，>=1024 隐藏 */}
  <MobileHeader />

  <main className="flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[240px_400px_1fr]">
    {/* Desktop Sidebar：<1024 隐藏（内容由 Drawer 承载） */}
    <aside className="hidden min-w-0 overflow-y-auto border-r … lg:block">
      <Sidebar />
    </aside>

    {/* Entry List：无选中时手机可见；有选中时手机隐藏、桌面始终显示 */}
    <section className={selectedEntryRef === null
      ? 'flex min-h-0 min-w-0 flex-col …'
      : 'hidden min-w-0 … lg:flex'}>
      <EntryList />
    </section>

    {/* Reader：有选中时手机可见；无选中时手机隐藏、桌面始终显示 */}
    <section className={selectedEntryRef === null
      ? 'hidden min-w-0 … lg:block'
      : 'min-w-0 … lg:block'}>
      <Reader />
    </section>
  </main>

  {/* Drawer（含 backdrop），仅 <1024 有意义，由 CSS 控制显隐 */}
  <MobileNavigationDrawer />
</div>
```

关键点：

- **不复制任何业务组件**：没有 MobileSidebar / MobileEntryList /
  MobileReader；同一 `Sidebar` / `EntryList` / `Reader` 组件，布局
  由 `lg:` class 与 `selectedEntryRef`（**既有**状态，只读）决定；
- `selectedEntryRef` 的读取发生在 App 组合层（推导 className），不是
  新状态、不复制 server state——这是"JS 只处理交互状态"的合法用法；
- `hidden lg:flex` / `hidden lg:block` 由 CSS media query 生效，
  无 `window.innerWidth`、无 `useWindowSize`、无 UA sniffing；
- 桌面 ≥1024 三栏行为与 0005/0006 一致（三栏各自滚动、`h-dvh`）；
- 手机单主内容区**只有一个纵向滚动面**（EntryList 或 Reader 自身的
  `overflow-y-auto`），body 不形成无限滚动，无双滚动混乱。

### MobileHeader.tsx（新组件）

`<1024px` 显示（`lg:hidden`），`>=1024px` 完全不存在于视觉布局：

```text
selectedEntryRef == null:
  [☰]  LumiRSS    当前 view 名 / feed 标题（轻量副文本）

selectedEntryRef != null:
  [← 返回]        feed 标题（或轻量 "阅读"）
```

- ☰ 菜单按钮：`aria-expanded`（反映 drawer 状态）、`aria-controls`
  （指向 drawer id）、accessible label（"打开导航"）；点击 → 
  `openMobileSidebar()`；
- ← 返回按钮：accessible label（"返回文章列表"）；点击 → 
  `selectEntry(null)`——**只做这一件事**，不 reload、不重新 fetch
  （返回已存在的 Entry List Query cache）；
- Reader 打开时**不显示** ☰（不同时堆 Menu + Back + toolbar）；
  Reader 的 Read/Star/原文按钮保留在 ReaderHeader 正文区域；
- 顶栏高度 ≥44px，`padding-top` 计入 `--safe-top`；
- 不显示 unread count（无 API，延续 0005 原则）。

### MobileNavigationDrawer.tsx（新组件）+ mobileSidebarOpen（状态方案）

**状态方案（按当前真实代码选定）：进入现有 Zustand store
`reader-ui.ts`。** 理由：`mobileSidebarOpen` 是纯 UI 状态，与
view/feed/entry selection 同类；且 drawer 的关闭时机（点导航项后）
发生在 `<Sidebar />` 内部的 store 调用路径上，放同一 store 语义最顺；
不创建第二个 state management system，也不需要把回调 prop 层层
穿过组件。

```typescript
// reader-ui.ts 新增（其余全部不动）
mobileSidebarOpen: false,
openMobileSidebar: () => set({ mobileSidebarOpen: true }),
closeMobileSidebar: () => set({ mobileSidebarOpen: false }),
```

Drawer 组件行为（`lg:hidden`，桌面永不出现）：

- 结构：`backdrop`（下层）+ `panel`（左侧滑入，含同一份 `<Sidebar />`）；
- **打开**：menu button → `openMobileSidebar()`；
- **关闭**：backdrop 点击 / drawer 内 ✕ 按钮 / Escape 键 / 点击
  任意导航项（All/Unread/Starred/All Feeds/feed）之后；
- **导航项点击后关闭（显式机制，非事件委托）**：`Sidebar` 组件接受
  可选 prop `onNavigate?: () => void`，仅在真正完成一次导航选择后
  调用——触发点为：All / Unread / Starred（`selectView`）、
  All Feeds / 具体 Feed（`selectFeed`）。Desktop 挂载
  `<Sidebar />`（不传，行为不变）；Mobile drawer 挂载
  `<Sidebar onNavigate={closeMobileSidebar} />`。**禁止**用
  `target.closest("button")` 之类的事件委托——那会让 Feed 加载失败
  的「重试」按钮等非导航按钮也误关闭 Drawer。Sidebar.tsx 因此允许
  这一个职责明确的最小修改（新增可选 prop + 导航 onClick 末尾
  `onNavigate?.()`），其余逻辑不动；
- **Escape**：drawer 打开时监听 keydown（Escape → close），关闭时
  移除监听；
- **语义（非 modal）**：drawer panel 是 navigation drawer landmark，
  不声明为完整 modal dialog；使用语义化
  `<aside aria-label="导航">`（或严格等价的 landmark 写法）；
  **不声明 `aria-modal="true"`**——0007 明确不实现 focus trap /
  modal focus containment / focus restore，声明 modal 语义却做不到
  modal 行为会造成语义与行为不一致。若未来升级为 `role="dialog"`，
  必须同时满足 WAI modal focus containment/restore——那是更复杂的
  路线，0007 有意不走；
- menu button 保持：`aria-expanded`（反映 drawer 状态）、
  `aria-controls`（指向 drawer id）、accessible label（"打开导航"）；
- backdrop 用真实 `<button aria-label="关闭导航">`（不把可点击 div 当
  button），z-index 低于 panel（backdrop 不覆盖 drawer）；
- Escape / close（✕）/ backdrop 点击关闭继续有效；
- **不做完整 focus trap**（不引入 focus-trap 依赖）：最低要求 =
  drawer 内按钮键盘可操作、Escape 可关、focus-visible 清楚；
  完整 modal 无障碍可以后续统一优化；
- **不引入** Radix / Headless UI / focus-trap / native dialog
  framework / 任何 drawer/dialog library——用现有 React + CSS
  （fixed 定位 + transition）实现。
- 打开时 panel 内滚动（feeds 多时可滚），body 不滚动（可选
  `overflow-hidden`，Build 按实测最小实现）；
- 结构与定位仍为 backdrop（下层）+ 左侧滑入 panel（含同一份
  `<Sidebar />`），纯 React + CSS 实现（见上）。

### View / Feed 变化语义（0005/0006 冻结行为，0007 保持）

```text
selectView() / selectFeed()
  → selectedEntryRef = null（既有行为）
```

因此：Reader 中打开 drawer → 选 Starred → selection 清空 → 手机
自动回到 Starred Entry List。逻辑自然成立，无需任何新代码。

### Mobile Reader Flow（冻结）

```text
Entry List → 点击 Entry → selectedEntryRef set → Reader 替换列表（全屏）
Reader    → 点 ← 返回   → selectEntry(null)    → 回到列表（cache 复用）
```

- 切换由 `selectedEntryRef`（既有状态）+ CSS class 推导，无
  `mobilePane` 第二状态；
- 返回**不 reload、不重新 fetch 整页**：TanStack Query cache 仍在，
  `useInfiniteQuery` 的已加载 pages 原样恢复显示；
- Reader 的 Detail 请求、DOMPurify 渲染、Read/Star mutation、
  invalidation 全部复用 0006 现有实现，**不为 Mobile 新建另一套
  API 调用**。

## Mobile UX 细则

### Touch target（约 44×44 CSS px）

所有主要移动端操作目标在 `<1024px` 达到 ≥44px 高度（宽度受内容
限制时至少 padding 足够），包括：menu、back、view buttons、feed
rows、entry row、Read/Unread、Star/Unstar、Retry、Load More、
drawer ✕。实现方式：Tailwind `max-lg:min-h-11`（44px）类响应式
调整，桌面视觉密度不变。不为视觉紧凑把按钮缩成难点的小图标。

### Hover 审计（不依赖 hover）

审计结论（已读当前代码）：收藏/未读状态是**常显 indicator**
（★、圆点），Back/Menu 是常显按钮，不存在"hover 才显示"的功能。
现有 `hover:bg-*` 只作为桌面 enhancement，全部保留；0007 只需保证
新组件同样不依赖 hover。

### Entry Row mobile

- 标题在 `<1024px` **wrap**（去掉 `truncate` 单行截断，允许自然
  折行；可选用 `line-clamp` 类限制在 2–3 行，但不能一行截到看不懂）；
- 保留：title / feedTitle / publishedAt / read / starred；author 已是
  条件渲染（缺失不占空间），维持；
- metadata 允许更紧凑布局（`max-lg:` 下缩小间距）；
- 不新增摘要正文；不固定行高；整行仍是 `<button>`。

### Reader mobile typography

- 正文容器：`px-8` → `max-lg:px-5`（约 16–20px 左右留白）；
- 桌面保持 `max-w-[44rem]`（~700px）+ `mx-auto` 不变；移动端
  `max-width` 不生效于窄屏，不构成额外固定宽度；
- 行高（1.75）与 `.article-content` 全部样式复用，不改排版系统；
- **不增加** Reader font settings。

### State controls on phone

ReaderHeader 的 Read/Star/打开原文 按钮在手机上保持可触摸
（`max-lg:min-h-11`）；容器已是 `flex flex-wrap`，空间不足时自然
折行成两行 toolbar。**禁止**缩成 20px 小图标、引入 overflow menu、
引入 dropdown library。

### Article overflow（移动端重点检查项）

现有 `.article-content` 已覆盖 `img{max-width:100%}`、
`pre{overflow-x:auto}`、`table{display:block;overflow-x:auto}`、
`word-break:break-word`。0007 补充核对：

- `code`（行内）长 token：`overflow-wrap:anywhere` 或等效
  （在 `.article-content code` 追加，一处改动）；
- `blockquote` / 长 URL 文本：已被 `word-break:break-word` 覆盖，
  Build 时以真实 390px 视口复核；
- 验收标准：一篇含 image/pre/table/长文本的真实 RSS 文章不能让
  **整个 App** 产生横向滚动（App 根容器本身不出现横向 overflow，
  溢出被限制在 pre/table 的局部滚动里）。

## Viewport / Safe Area / Height / Scroll（冻结）

### Viewport（index.html 最小修改）

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

（当前已有 `width=device-width, initial-scale=1.0`，最小修改只补
`viewport-fit=cover`，不重复添加 meta。）

### Safe Area（四方向）

`index.css` 的 `:root` 新增四个 CSS variables（集中定义，不散落）：

```css
:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-right: env(safe-area-inset-right, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
  --safe-left: env(safe-area-inset-left, 0px);
}
```

四个方向都定义的原因：portrait（竖屏）主要是 top/bottom（刘海 /
Home indicator），但 landscape（横屏）下 notch / 圆角屏可能占用
left/right。

使用位置（仍集中、少量）：MobileHeader（顶部 padding）、
MobileNavigationDrawer 外层 safe area、EntryList footer 与 Reader
正文的底部 padding；左右方向在上述外层容器使用
`max(normalPadding, safeInset)` 语义（当前 CSS 下的最小等价实现，
如 `padding-inline: max(1rem, var(--safe-left)) max(1rem, var(--safe-right))`）。不创建
safe-area abstraction/library，不逐组件散落。

### Height

继续 `h-dvh`（已在用）。不回退 `100vh`。

### Scroll

桌面三栏各自滚动（现状保持）；手机单主内容区唯一纵向滚动面
（EntryList 或 Reader 容器的 `overflow-y-auto`），body 不出现
双滚动。

## PWA

### manifest.webmanifest（新增静态文件，内容冻结）

`apps/web/public/manifest.webmanifest`（手写静态文件，**不用任何
PWA plugin 生成**）：

```json
{
  "id": "/",
  "name": "LumiRSS",
  "short_name": "LumiRSS",
  "description": "流光阅源 — 单用户自托管的 RSS 阅读器",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#ffffff",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

- 颜色与当前 UI 协调：`background_color`/`theme_color` = `--surface`
  (#ffffff，浅色 UI 的阅读面)；图标使用现有 favicon 的紫色系
  (#863bff 家族) 主体 + 白底——不创造新品牌主题；
- **不包含**：shortcuts / share_target / file_handlers /
  protocol_handlers / screenshots / related_applications /
  orientation / launch_handler——保持最小；
- 纯静态公开 metadata：不含任何 API URL、FreshRSS 地址、密码、
  token、用户数据。

### index.html metadata（最小追加）

```html
<link rel="manifest" href="/manifest.webmanifest" />
<meta name="theme-color" content="#ffffff" />
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
```

（`favicon.svg` 的 link 保留；不重复、不删除既有 meta。）

### Icons

目录（全部 repo local assets，不通过 CDN / 外部 URL 加载）：

```text
apps/web/public/icons/
├── lumirss-icon.svg        # 源文件（普通版参考）
├── icon-192.png            # 192×192 PNG
├── icon-512.png            # 512×512 PNG
├── icon-maskable-512.png   # 512×512 maskable PNG
└── apple-touch-icon.png    # 180×180 PNG
```

**设计原则**：Build 时优先复用仓库唯一既有品牌资产
`apps/web/public/favicon.svg`（紫色光流图形）。以其为主体：普通版 =
白底 + 居中图形；maskable 版 = 整幅 512×512 铺满背景（白/浅紫），
主体缩放到中央圆形 safe zone 内（直径约 70%，比标准最小安全区
80% 更保守，细节不贴边）；apple-touch-icon =
180×180 白底 + 居中图形。如需为不同尺寸微调（favicon.svg 含大量
filter 效果，小尺寸渲染可能糊），允许手写一个简化的
`lumirss-icon.svg`（同色系的"L / 光流"简单几何），**不开启品牌
Logo 重设计项目、不下载第三方 Logo、不使用 copyrighted asset、
不使用在线 icon generator、不引入 icon package**。

**栅格化方法（按本机实测工具事实冻结的方案 + 回退）**：

0. 本机不存在 ImageMagick / Inkscape / rsvg-convert / chromium CLI /
   PIL / cairosvg（Spec 阶段已逐一实测），**禁止**为此安装任何
   依赖（`pnpm add sharp`、`npm install canvas`、
   `sudo apt install imagemagick` 等一律不做）；
1. **首选方案（canvas 导出，像素精确）**：使用当前 Qoder 环境已
   提供的托管浏览器工具（playwright / browser-use MCP）的 JS
   evaluate 能力：
   ```text
   SVG 字符串
   → 构造 Image，绘制到 canvas（intrinsic 像素尺寸）
   → canvas.toDataURL("image/png")
   → Node Buffer.from(base64, "base64") 写为 PNG 文件
   ```
   `canvas.width` / `canvas.height` 分别精确设为
   **192×192 / 512×512 / 180×180**（maskable 复用 512×512 画布但
   主体缩小到安全区）。输出像素**不依赖 viewport CSS 尺寸或
   devicePixelRatio**——canvas 的 width/height 属性就是输出 PNG
   的像素尺寸。临时脚本/HTML 放 `/tmp`，**不进仓库**；
2. **回退方案（精确尺寸截图）**：仅当托管浏览器不支持
   canvas/evaluate 导出时，才尝试 exact screenshot rasterization
   （`browser_resize` 到精确像素 + `browser_take_screenshot`）。
   截图产出的 PNG **只有**在真实像素尺寸通过 IHDR 解析与 `file`
   命令双重验证后才能接受；
3. **最终回退**：两者都不可用（0006 曾遇到浏览器下载被网络阻断）→
   **STOP and report**，由用户决定（用户自行提供 PNG / 用户批准
   其它工具）。**不得提交错误尺寸或伪 PNG / 改扩展名文件。**

**验证**（不新增依赖，全部保留）：用已有 `file` 命令确认每个 PNG
的真实格式与尺寸（如 `file icon-512.png` → "PNG image data,
512 x 512"）；自动化层面用 Vitest + `node:fs` 直接解析 PNG IHDR
字节（offset 16 起的大端 width/height）断言尺寸——纯 Node，零依赖。
canvas 方案产出的 PNG 同样必须通过这套验证（对首选与回退方案
一视同仁）。

### Installability / 安装行为（冻结）

- **不做**自定义安装按钮：禁止 beforeinstallprompt、Install App
  按钮、install banner、安装教程 modal、iOS 教程弹窗。原因：平台
  差异大、iOS 不支持 beforeinstallprompt；让用户使用浏览器原生
  Install / Add to Home Screen 即可；
- Standalone 安装后无完整浏览器地址栏，应用逻辑与 Browser 模式
  **同一套代码**，不为 standalone 建第二个 App；
- Secure context：开发用 Vite localhost 验证；生产 HTTPS 属于后续
  Caddy / Production milestone，0007 不开始配置。

### No Service Worker（冻结，写进 AC）

- 0007 不注册、不实现任何 Service Worker；不出现 Workbox /
  vite-plugin-pwa / API cache / offline article cache；
- 禁止为 PWA 新增 IndexedDB / localStorage article cache /
  Cache Storage——server state 仍由 TanStack Query 管，Zustand 仍为
  UI state，不打破 0005 状态架构；
- 断网时现有 Query Error UI 正常工作即为正确行为；
- Manifest / README / UI 一切文案**不得**声称离线阅读能力。

## 预计文件变化（以当前真实代码为基准的上限）

新增：

```text
apps/web/public/manifest.webmanifest
apps/web/public/icons/{lumirss-icon.svg, icon-192.png, icon-512.png,
                       icon-maskable-512.png, apple-touch-icon.png}
apps/web/src/components/MobileHeader.tsx
apps/web/src/components/MobileNavigationDrawer.tsx
apps/web/src/__tests__/mobile-navigation.test.tsx   # Test A/B/C/D + a11y
apps/web/src/__tests__/mobile-reader.test.tsx       # Test E/F/G
apps/web/src/__tests__/pwa-manifest.test.ts         # Test H + HTML meta + PNG 尺寸
```

修改：

```text
apps/web/index.html        # viewport-fit=cover + manifest/theme-color/apple-touch 链接
apps/web/src/App.tsx       # 响应式布局 + MobileHeader + Drawer 组合
apps/web/src/index.css     # 四方向 safe-area variables + 少量 mobile 样式（code overflow 等）
apps/web/src/components/EntryRow.tsx       # 手机标题 wrap + touch target
apps/web/src/components/EntryList.tsx      # Load More/Retry touch target（小改）
apps/web/src/components/Reader.tsx         # 手机 padding（max-lg:px-5）+ 底部 safe-area
apps/web/src/components/ReaderHeader.tsx   # 按钮 touch target（max-lg:min-h-11）
apps/web/src/components/Sidebar.tsx        # 仅新增可选 onNavigate prop（导航完成后回调，
                                           #   desktop 不传行为不变）
apps/web/src/store/reader-ui.ts            # 仅新增 mobileSidebarOpen 三个成员
```

预计零改动：`api/*`（client/queries/types 全部不动）、
`sanitize-article-html.ts`、`safe-external-http-url.ts`、
`main.tsx`、`vite.config.ts`、`services/bff/**`（**BFF diff 必须为 0**）。

不创建 `mobile/` / `pwa/` / `platform/` / `device/` / `responsive/` /
`navigation-system/` 目录。

## Testing strategy

沿用 0005/0006 模式：vitest + jsdom + RTL + `vi.stubGlobal('fetch', …)`
mock，无真实网络、无真实 secret。**数量由行为自然决定，不凑数。**

### jsdom 边界（诚实声明）

jsdom 不计算 CSS layout，**不能**用 Vitest 证明"390px 没有 overflow"。
自动测试只验证 interaction / state / DOM semantics；真实宽度与排版
必须用真实浏览器（Browser/Preview）或人工验证，报告中明确区分。

### Mobile pane 切换的断言方式

list/reader 的手机显隐由 `hidden lg:flex` class 实现，jsdom 不加载
CSS，`toBeVisible()` 不可用。测试断言 DOM class 语义（如
`section` 含/不含 `hidden` class）——这是 DOM-level 断言，明确它
是"语义近似"，真实视觉效果归浏览器 smoke。

### Test A — Drawer closed by default

Mobile 下 drawer 不渲染（或不可见），menu button 存在且可用，
`aria-expanded="false"`。

### Test B — Open / Close

点 menu button → drawer 打开（`aria-expanded="true"`，drawer 节点
存在）；backdrop 点击 / ✕ / Escape → 关闭。

### Test C — View selection

drawer 打开 → 点 Unread → `view === "unread"`、drawer 关闭、
`selectedEntryRef === null`。

### Test D — Feed selection

drawer 打开 → 点某 feed → `selectedFeedUrl` 正确、drawer 关闭；
点 All Feeds → `selectedFeedUrl === null`、drawer 关闭。

### Test E — Entry → mobile Reader

`selectedEntryRef = null` → list section 无 `hidden`、reader section
含 `hidden`；点击 Entry → `selectedEntryRef` set → reader section
无 `hidden`、list section 含 `hidden`。

### Test F — Reader back

Mobile Reader 中点 ← 返回 → `selectEntry(null)` 生效 → list 恢复
可见；**断言无额外 fetch 发生**（不 reload、不重新请求列表）。

### Test G — Reader business regression（mobile 下）

手机布局中 Reader 仍：加载 Detail（真实发起 `GET /entries/{ref}`）、
安全正文渲染（DOMPurify 路径）、Read/Star 按钮可用且发出正确
PATCH body——复用 0006 组件，测试确认组合层未破坏。

### Test H — Manifest 自动验证（纯 Node，零依赖）

Vitest 读取 `public/manifest.webmanifest`，`JSON.parse` 成功，断言：
`name` / `short_name` / `start_url` / `scope` 存在、
`display === "standalone"`、icons 含 192×192 与 512×512；
同文件断言 `index.html` 含 `link[rel=manifest]`、`apple-touch-icon`
link、`theme-color` meta、viewport 含 `viewport-fit=cover`（且
viewport meta 只出现一次，不重复）。

### Icon 文件自动验证（纯 Node，零依赖）

读取各 PNG 文件：PNG signature（8 字节魔数）正确；解析 IHDR 断言
`icon-192` 为 192×192、`icon-512` / `icon-maskable-512` 为 512×512、
`apple-touch-icon` 为 180×180。不以文件名猜测尺寸。

### Drawer accessibility 断言

menu button `aria-expanded` false→true 切换；drawer panel 为
`<aside aria-label="导航">`（或等价 landmark）且**不含**
`aria-modal`；非导航按钮（如 Feed 加载失败的「重试」）点击后 drawer
**不**关闭；Escape 关闭。不要求完整 focus trap test。

### 既有回归

所有既有 0005 + 0006 Web 测试行为无 regression（不为 mobile 重写
业务测试；个别测试如因 DOM 结构调整需要最小更新——例如 App 布局
包裹层变化导致的查询——允许最小修改并在报告中说明，不得删除行为
断言）；全部既有 BFF 测试通过（`uv run pytest`）。Build 前观测
baseline：Web 97 passed / BFF 121 passed（仅作参考记录）；**AC
不要求最终恰为 97 / 121**——0007 新增测试会自然增加前端总数，
最终报告以实际 `XX frontend passed / YY backend passed` 为准。

## Acceptance Criteria（AC1–AC28）

| # | 标准 |
|---|---|
| AC1 | 所有修改位于 `feat/0007-mobile-pwa` |
| AC2 | Build 开始前 baseline 健康（`pnpm test` / `pnpm lint` / `pnpm build` / `uv run pytest` 全绿；观测参考值 Web 97 / BFF 121，非最终 AC 数字） |
| AC3 | ≥1024px 桌面三栏布局无 regression（Sidebar/List/Reader 可用） |
| AC4 | <1024px 不再出现三栏硬挤布局：Mobile Header + 单主内容区 |
| AC5 | Menu → Drawer 打开；backdrop/✕/Escape/View/Feed 选择后关闭；View/Feed selection 工作且自动关 Drawer |
| AC6 | 手机流程 Entry List → 点 Entry → Reader → ← 返回 → Entry List 全通，返回不 reload（无多余 fetch） |
| AC7 | Mobile 未复制任何 server state（entries/detail/read/star 不进第二 store） |
| AC8 | 同一套业务组件；无 Desktop/Mobile 两套 Reader/List/Sidebar 复制（允许 MobileHeader/Drawer 两个新交互组件） |
| AC9 | 核心 controls 在 <1024px 达到 ~44px touch target；关键功能不依赖 hover |
| AC10 | viewport 含 `viewport-fit=cover`；四方向 safe-area 通过 CSS variables 有效处理（Mobile Header/Drawer 外层/List footer/Reader 底及左右 max(padding, inset)） |
| AC11 | 真实 RSS（image/pre/table/长文本）不造成整个 App 横向 overflow |
| AC12 | 真实检查 390 / 430 / 768 视口（390 为重点：菜单、drawer、view/feed 切换、列表滚动、进 Reader、返回、正文、Read/Star 全通） |
| AC13 | 真实确认 1024 / 1280 / 1440 无桌面 regression |
| AC14 | `manifest.webmanifest` 存在且有效：name/short_name/start_url/scope/display=standalone/icons |
| AC15 | 真实 192×192 与 512×512 PNG（file 命令 + PNG IHDR 自动验证双重确认），存在合理 maskable icon（主体在安全区内） |
| AC16 | apple-touch-icon 存在且为真实 180×180 PNG 资产 |
| AC17 | 真实 dev server 下 `GET /manifest.webmanifest` 与全部 manifest icon URL 均 HTTP 200，Content-Type 合理 |
| AC18 | Manifest 正确定义 `display: "standalone"` |
| AC19 | 无 Service Worker：不注册、不实现；无 Workbox / vite-plugin-pwa / API cache / offline article cache |
| AC20 | 项目任何文案不声称 offline reading |
| AC21 | 0 new direct dependencies（package.json 无新增） |
| AC22 | 所有既有 Web behaviors/tests 无 regression；全部 Web 自动测试实际通过（报告真实 `XX frontend passed`；总数自然高于 baseline，不算失败） |
| AC23 | 所有既有 BFF tests 无 regression；全部通过（报告真实 `YY backend passed`）且 `services/bff` diff = 0 |
| AC24 | `pnpm lint` / `pnpm build` 真实通过 |
| AC25 | Drawer/menu/back/entry/state 操作具备最低 keyboard/aria 语义（aria-expanded/aria-controls/aside landmark + aria-label/Escape/真实 button 元素；drawer 无 aria-modal） |
| AC26 | Installability 前置条件（manifest/icons/start_url/display/secure context）满足；浏览器确认 manifest 被识别（`link[rel=manifest]` 可寻址）；OS 级真实安装如无法由 Agent 完成，明确记录为 USER/MANUAL VERIFICATION，不假装安装过 |
| AC27 | 无越界：Offline / Service Worker / Push / Router / native app / Dark Mode / AI / RSSHub / Caddy 均未实现 |
| AC28 | 全部通过后 Phase 3 — Reading Experience 标记 Completed；0008 只标 Next，不启动 |

## Tasks（批准后严格逐步执行，每步完成即验证）

1. **Baseline check**：`node --version` / `pnpm --version`；
   `cd apps/web && pnpm test && pnpm lint && pnpm build`；
   `cd services/bff && uv run pytest`。失败 → 停止报告，不算 0007。
2. 复核现有 responsive / Reader 代码（以实际代码为准冻结实现细节）。
3. `reader-ui.ts` 新增 `mobileSidebarOpen` + open/close；`index.css`
   新增四方向 safe-area variables。
4. `MobileHeader.tsx`（menu/back + scope 标题 + safe-area）。
5. `Sidebar.tsx` 新增可选 `onNavigate` prop；
   `MobileNavigationDrawer.tsx`（backdrop + panel + Sidebar 复用 +
   onNavigate 导航关闭 + Escape）→ **Test A/B/C/D + a11y 断言**。
6. `App.tsx` 响应式改造（`lg:` grid + selectedEntryRef 驱动
   list/reader class）→ **Test E/F**（含无多余 fetch 断言）。
7. Touch target + hover 审计（EntryRow/EntryList/ReaderHeader 按钮
   `max-lg:min-h-11` 等）。
8. Viewport / safe area 落地（index.html `viewport-fit=cover`；
   MobileHeader/List footer/Reader 底部 inset）。
9. Entry Row mobile（标题 wrap、紧凑 metadata）。
10. Reader mobile typography / overflow（`max-lg:px-5`、code
    overflow-wrap；复核 img/pre/table/长词）。
11. **Test G**（mobile Reader 业务回归）+ 全量前端回归（既有 97 个
    测试 + 新增全部测试）。
12. 创建 `public/manifest.webmanifest`（冻结内容）。
13. 检查既有品牌资产（favicon.svg）→ 制作 `lumirss-icon.svg`
    （普通版 + maskable 安全区版；仅用现有浏览器工具栅格化，
    见 Icons 方案；不可用 → 停止报告）。
14. 产出 `icon-192/512/maskable-512/apple-touch-icon` PNG
    （临时 HTML 放 /tmp，不进仓库）。
15. `index.html` 追加 manifest / theme-color / apple-touch 链接。
16. Manifest / icon / HTML metadata 自动检查（**Test H** + PNG IHDR
    验证 + `file` 命令复核）。
17. `pnpm test` → `pnpm lint` → `pnpm build`。
18. BFF 回归：`cd services/bff && uv run pytest`（diff 必须为 0）。
19. 真实浏览器 responsive smoke：启动 FreshRSS + BFF + Vite，逐个
    检查 390×844 / 430×932 / 768×1024 / 1024×768 / 1280+（前三个为
    Mobile/Tablet 重点；1024+ 验证桌面无 regression）。尽力截图
    （390 Entry List / 390 Drawer / 390 Reader / 768 / 1280），无
    截图能力的项明确标 VERIFIED / PARTIALLY / UNVERIFIED。
20. 真实 PWA smoke：`GET /manifest.webmanifest` → 200 + Content-Type
    合理；manifest 内 icon URL 全部 → 200；浏览器 document 能找到
    `link[rel=manifest]`。如浏览器工具支持：验证 manifest 被识别；
    OS 级安装不可行则记 manual verification。
21. Secret / dependency / scope 扫描（tracked + untracked-not-ignored：
    无 FRESHRSS_* / token / Authorization / .env 内容；不读取
    gitignored .env；package.json 无新增依赖；node_modules/dist 未进
    git；/tmp 临时文件未进仓库；manifest 无任何 secret）。
22. 文档更新：README（Responsive 支持 / 手机行为 / PWA manifest /
    安装基础 / 开发验证方法；**不写 offline**）、PROJECT_STATE
    （Implemented 增加各项 + 明确 Offline/Service Worker 未实现；
    Phase 3 → Completed；Next → 0008）、Project Board
    （0007 → completed）、devlog 0007。
23. Final git 检查：`git branch --show-current` / `git status
    --short --branch` / `git diff --stat` / `git diff --check` /
    `git diff` → **停在工作区等待人工 Review**（不 commit / 不
    push / 不建 PR；不开始 0008）。

## Verification

```bash
cd apps/web && pnpm test && pnpm lint && pnpm build
cd ../../services/bff && uv run pytest            # 全绿（观测 baseline 参考 121；报告实际 YY passed）；diff = 0
git branch --show-current                          # feat/0007-mobile-pwa
git status --short --branch                        # 仅预期文件
git diff --stat / --check                          # 无越界、无空白错误
file apps/web/public/icons/*.png                   # 真实 PNG 尺寸
# 真实 dev server（FreshRSS + BFF + Vite）下：
curl -I http://localhost:5173/manifest.webmanifest          # 200
curl -I http://localhost:5173/icons/icon-192.png            # 200
# 浏览器 responsive 检查：390 / 430 / 768 / 1024 / 1280 / 1440
```

## Error 处理原则（遇到问题时）

先判断问题层（Node / pnpm / Vite / Tailwind 响应式 class / React 组合 /
TanStack Query / CSS / safe-area / viewport / manifest / icon 生成 /
tests / 浏览器工具），按"现象 → 证据 → 问题层 → 原因 → 最小修复"
报告。**Mobile/PWA 不应触碰 BFF**：如果觉得需要改 `services/bff` →
停止并报告。浏览器工具不可用（截图 / resize / rasterize）→ 如实
标记 UNVERIFIED / 停止报告，不假装验证过。

## Documentation updates（AC 全过后单独做）

- **README**：增加 Responsive support（<1024 drawer + 单栏模式说明）、
  Phone/Tablet 行为、PWA manifest 说明、安装基础（"使用浏览器提供的
  Install / Add to Home Screen"，不写各平台长教程）、开发验证命令；
  **禁止**出现 Offline / Offline Reader / Background Sync / Push 字样。
- **PROJECT_STATE**：Implemented 增加 Responsive mobile layout /
  Mobile navigation drawer / Mobile Reader flow / Touch-friendly
  controls / Safe-area support / PWA manifest / PWA icons /
  Standalone installability metadata；Not implemented 中明确保留
  Offline support / Service Worker；Current phase → Phase 3 Completed；
  Next → 0008 — RSSHub。
- **Project Board（project-data.js）**：0007 → completed（填
  implemented/acceptance/problems/learned + devlog 链接）、0008 →
  next、phase-3 → completed、currentPhaseId/currentMilestoneId /
  updatedAt 更新。
- **Devlog `docs/devlog/0007-mobile-pwa.md`**：Status / Goal /
  Responsive architecture / Why CSS-first responsive / Why
  selectedEntryRef drives mobile Reader / Mobile drawer / Safe areas /
  PWA manifest / PWA icon generation method（如实记录用什么工具栅格化、
  遇到什么问题）/ Why no Service Worker / Installability verification /
  Actual viewport checks / Tests / Lint / Build / Problems / Solutions /
  What I learned / Next milestone。不记录 secret / token / 完整文章
  正文 / AI internal reasoning / 无意义 build log。

## 最终解释义务（完成后向初学者解释，内容已包含在本 Spec Context 节）

Responsive Design（为什么不是再写一份手机版 React）、Breakpoint
（为什么 <1024 / ≥1024）、Drawer（与 Desktop Sidebar 的关系）、
Mobile Reader Flow（为什么 selectedEntryRef 不需要第二个 page
state）、CSS vs JS responsive、Safe Area（env(safe-area-inset-*)）、
100dvh vs 100vh、Touch target（为什么 44px）、PWA 是什么、Manifest
控制什么、Standalone 与浏览器 tab 的区别、Secure Context（为什么
localhost 可验证、生产要 HTTPS）、Service Worker 是什么以及为什么
0007 故意不实现、Installability ≠ Offline、Maskable Icon 为什么
会被裁剪。

## Risks / Unknowns

- **Icon 栅格化是最大风险**：本机无任何 CLI rasterizer（已实测），
  方案依赖 Qoder 托管浏览器工具的 resize + 截图能力；0006 曾遇到
  浏览器下载被网络阻断。若不可用 → 停止并报告，由用户决定
  （用户自行生成 PNG 或批准其它方式），绝不安装依赖、不提交伪 PNG。
- **浏览器 resize / 截图能力**：真实视口检查（390/430/768）依赖
  浏览器工具的可控 resize；0006 devlog 记录过 `window.resizeTo`
  被忽略的情况。若无法真实 resize → 相关 AC 标 UNVERIFIED /
  PARTIALLY，请用户人工确认，不假装 PASS。
- **OS 级真实安装**：Agent 环境大概率无法完成真实安装；AC26 按规定
  区分 "installability prerequisites PASS" 与 "actual OS install →
  USER/MANUAL VERIFICATION"。
- **Tailwind v4 变体叠加**（`lg:max-[1100px]:`）：如验证有异常，
  退化为统一 240/400 列宽（非布局模式变化），devlog 记录。
- **既有测试的 DOM 结构耦合**：App 布局重组可能使个别 0005/0006
  测试的容器查询需要最小更新；只允许最小修改且不删行为断言，
  报告中逐条说明。
- **Vite 对 .webmanifest 的 Content-Type**：预期
  `application/manifest+json`（AC17 以真实响应为准，"reasonable"
  即可，不为此改 Vite 配置）。
- **jsdom 无法验证 CSS layout**：全部视觉类 AC 依赖真实浏览器 /
  人工，报告明确分级。

---

**本 Spec 为 Draft。在用户明确回复"批准 Spec，可以开始 Build"之前，
不修改任何仓库文件（本 Spec 自身除外）、不安装依赖、不创建图标、
不修改 manifest、不写 Service Worker、不开始 Build 的任何步骤。**
