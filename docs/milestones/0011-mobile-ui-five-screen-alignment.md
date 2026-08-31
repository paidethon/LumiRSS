# 0011 — Mobile UI Navigation & Five-Screen Alignment

> 状态：**Completed**（PR #17, `fac3891` + PR #18 fix, `dd95924`）
> 日期：2026-08-30
> 依据：用户提供的 Spec0011 Bundle（Qoder-Spec0011-Prompt.md + 五张参考图）
> 前置：0009（UI Reboot）、0010/0010a（Settings Center & Adaptive Shell）已合入 main（PR #16，43f8ae8）

---

## Goal

让移动端 Web（<1024px，重点 <768px）的**首页、订阅、搜索、收藏、侧边栏**五个界面在
信息架构、交互语义与视觉层级上对齐用户提供的五张参考图，同时：

1. 保持 Lumi Mist / 雾光视觉语言，不机械复制参考图像素、示例数据或第三方资产；
2. 在现有 React + TS + Tailwind v4 + TanStack Query + Zustand 代码上演进，不另起炉灶；
3. 建立清晰的移动端一级导航模型（AppSection），设置入口统一收敛到侧边栏品牌区右上角；
4. 数据契约零造假：BFF 没有的字段/能力，UI 诚实降级或标注 planned，不伪造。

## 前置条件核对（Gate 0 已真实核验，2026-08-30）

```text
Git:        main @ 43f8ae8（PR #16 已合并），工作区干净（仅未跟踪的任务 zip）
分支:       feat/0011-mobile-ui-five-screen-alignment（从 main 新建）
Web 测试:   pnpm test / pnpm lint / pnpm build（apps/web，vitest + oxlint + tsc）
BFF 端点:   /api/v1/feeds、/api/v1/entries、/api/v1/entries/{ref}、
            /api/v1/entries/{ref}/state（无 search、无 category、无 unread count）
Feed 契约:  { title, feedUrl }（仅两字段）
EntryListItem 契约: entryRef/title/feedTitle/author/url/publishedAt/read/starred
导航状态:   Zustand reader-ui { view(all|unread|starred), selectedFeedUrl,
            selectedEntryRef, mobileSidebarOpen }——无 AppSection 概念
路由:       无路由库；Playground 为 dev-only hash 路由（#/playground）
图标:       lucide-react 已安装（1.34.0），继续沿用
```

## Context — 概念解释（写给初学者）

- **AppSection vs EntryView**：`EntryView`（all/unread/starred）描述"文章列表按什么过滤"；
  本 Spec 新增 `AppSection`（home/subscriptions/search/favorites）描述"用户在哪个一级页面"。
  两者是正交概念：收藏页内部使用 `starred` 这个 EntryView 复用现有查询，而不是复制数据。
- **disclosure / accordion**：可折叠区块的标准可访问性模式，按钮带
  `aria-expanded` + `aria-controls`，内容区由按钮控制显隐。侧边栏"RSS 订阅"根节点
  与订阅页的分类分组都采用该模式。
- **导航岛（floating tab bar）**：参考图中底部导航是悬浮圆角容器（左右留 inset、
  考虑 safe-area），而非贴边矩形条。需提供不支持 backdrop blur 的实色降级。
- **诚实降级**：后端没有缩略图/摘要/分类/未读数时，UI 不留空占位、不造假数据，
  而是退化为文本布局或不显示该元素。

## Scope（只做这些，按 Gate 划分）

### Gate 1 — Shared Navigation Shell

- 新增 `AppSection` 判别联合 + Zustand 状态（section 切换保留 home 的 view/selectedFeedUrl）；
- MobileTabBar 改为四入口：首页 / 订阅 / 搜索 / 收藏（导航岛形态，safe-area，≥44px，aria-current="page"）；
- 设置从底栏与侧边栏底部移除，统一到 SidebarHeader 品牌区右上角圆形图标按钮
  （桌面开 SettingsModal，移动开 MobileSettingsScreen——同一语义位置）；
- 共用 `MobilePageHeader`（三列 grid：44px 左操作 / 居中标题 / 44px 右操作）；
- Reader 打开时隐藏底栏，返回恢复页面与状态；
- 768–1023px 保持现有 Drawer + list/detail；≥1024px 桌面 shell 不受影响。

### Gate 2 — Sidebar Source Tree

- SidebarHeader（LumiRSS + 流光阅源 + 右上角设置按钮）复用于移动抽屉与桌面侧栏；
- "RSS 订阅"改为 disclosure：新会话默认收起，展开后显示 feed 列表（aria-expanded/controls + chevron）；
- 无分类契约时仅显示真实"未分组"，禁止编造"设计/AI"等分类；
- 工作区组去重：只保留 `时间线`、`收藏`（去掉"ME 时间线 · X"冗余前缀；"未读"作为时间线的过滤子项按现有语义实现）；
- Phase 2 planned 项维持"可见禁用 + 徽标"策略，不重复出现；
- 抽屉补齐：背景滚动锁定、关闭后焦点恢复；**升级为完整 modal 语义（focus trap + 初始焦点 + 焦点恢复，复用/增强 Sheet primitive）**（用户已批准）；

### Gate 3 — Home & Shared Entry Cards

- 首页：MobilePageHeader 居中动态 scope（全部信息流/未读/某订阅源），右侧真实过滤入口；
- 移动端卡片式列表：现有日期分组（今天/昨天/更早，entry-groups 已有）+ 更宽更紧凑的卡片；
- 共享 `EntryCard` 组件（真实字段内的层级：来源→时间/状态→标题；无摘要/缩略图时文本退化）；
- 收藏页 FavoritesPage：复用 starred 查询 + EntryCard，最近/更早分组；
- 星标写入沿用 useEntryStateMutation（乐观更新失败回滚已在 0009 实现，保持）。

### Gate 4 — Subscriptions & Search Surfaces

- 订阅页 SubscriptionsPage：真实只读 feed 信息（复用 useFeeds）+ 搜索框（本地过滤，文案诚实）；
  添加 RSS/OPML/分组管理禁用并标注 milestone `0012`（订阅 CRUD 属 Unified Subscription Center）；
- 搜索页 SearchPage：搜索框 + 搜索历史（本地 UI 数据，上限 + 单条删除/清空）+
  诚实"全局搜索能力尚未接入"空态（用户已批准：0011a 候选策略，本 Spec 零 BFF）；
  **不把已加载一页文章的过滤冒充全局搜索**；如提供本地过滤，文案必须为"在已加载内容中搜索"；
- "热门搜索"直接省略（无可信来源）。

### Gate 5 — Visual, Responsive & A11y Pass

- 五页面 Playground fixtures（#/playground 扩展：mobile-sidebar/home/subscriptions/search/favorites）；
- 七视口截图矩阵（360/390/430/768/1024/1280/1440），light 全量 + 侧栏/首页/收藏 dark；
- 修复 overflow、safe-area、焦点、对比度、触控问题；一次集中 polish + 一次复核。

### Gate 6 — Regression, Docs & Handoff

- 全量 test/lint/build；文档同步（见 Documentation updates）；逐文件交付报告；等验收后 commit。

## Non-goals（明确不做）

- 原生 App、第二套移动前端、路由库（现有无路由架构保持，AppSection 走 store）；
- 订阅 CRUD/OPML/分组持久化/拖拽排序（→ 0012 Unified Subscription Center）；
- RSSHub 路由发现（→ 0013）、AI 能力（→ 0014/0015）；
- 全局搜索 BFF 契约（用户已批准 0011a 候选策略，本 Spec 不实现）；
- 前端添加 excerpt/thumbnailUrl/category/readTime/favicon 等后端不存在的字段；
- 复制 Folo icons/mgc、参考图示例内容（Midjourney/OpenAI/IT之家等）与随机图片。

## 硬边界（冻结，0011 不得触碰）

1. BFF 零改动（除非用户单独批准新契约，本 Spec 默认零 BFF）；
2. 浏览器不直连 FreshRSS/RSSHub；不暴露凭据；
3. EntryView 语义不重载（subscriptions/search 不是 EntryView）；
4. read/starred 集合语义、cursor 不透明性、sanitize 边界不动；
5. 打开文章不自动标已读（0009 行为保持）；
6. Zustand 不存服务端数据；
7. 桌面（≥1024px）三栏 shell 与 0010 分栏/折叠/持久化行为不回退。

## 设计规格（冻结基线）

### AppSection 状态模型

```ts
type AppSection = 'home' | 'subscriptions' | 'search' | 'favorites'
// reader-ui 增加 section（默认 'home'）；
// 首页保留 view + selectedFeedUrl；切 section 不清空 home 的筛选状态；
// selectFeed/view 语义不变，但移动端 feed 导航后 section 应回 'home' 并关抽屉。
```

### MobileTabBar（导航岛）

- 四等宽 tab（首页/订阅/搜索/收藏），图标 + 文字垂直排列，min 44×44；
- 悬浮圆角容器：左右 inset（clamp），底部 `env(safe-area-inset-bottom)`；
- 轻边框 + 克制阴影 + 统一圆角；半透明/blur 仅点缀，必须实色降级；
- active = accent 色 + 字重/填充变化（不只靠颜色）；`aria-current="page"`；
- Reader 打开（selectedEntryRef != null）或全屏设置页打开时隐藏；
- 页面内容预留动态底部 padding，最后一条不被遮挡。

### MobilePageHeader

- 三列 grid：`44px 左操作 | 1fr 居中标题 | 44px 右操作`，标题真正居中；
- 左侧菜单（Reader 中为返回）；右侧仅真实可用操作，无功能时等宽占位；
- 不渲染系统状态栏；sticky 需处理滚动阴影与 safe-area。

### SidebarHeader / SourceTree

- SidebarHeader：LumiRSS + 流光阅源 副标题 + 右上角圆形设置 IconButton；
- RSS 根节点 disclosure，新会话默认收起；展开后平铺真实 feeds（无分类字段→"未分组"组）；
- feed 行：柔彩圆点（现有 feedColor 哈希）+ 真实标题 truncate + title 可访问名称；
- 选中 feed → section 回 home + 更新 scope + 关移动抽屉（现有 onNavigate 语义）。

### EntryCard（共享卡片）

- 层级：feedTitle(+圆点) · 时间 · 未读/已读 · 星标 → 标题（未读 medium）；
- 无缩略图/摘要契约 → 纯文本卡片（不留空洞）；
- 未读不只靠圆点（字重 + 可配置圆点，沿用 0010 设置）；
- 长标题 line-clamp；已读 dimRead 沿用设置。

### 订阅页 / 搜索页 / 收藏页

- 订阅页：Header（菜单/居中"订阅"/真实可用右侧动作）+ 本地过滤搜索框 +
  未分组折叠列表；CRUD 动作禁用 + `0012` 徽标；
- 搜索页：Header 居中"搜索" + 提交/清空/取消/键盘操作 + 历史（上限 10、单条删/清空）+
  "全局搜索尚未接入" EmptyState；
- 收藏页：Header（菜单/居中"收藏"/真实 filter）+ starred 查询 + 最近收藏/更早分组 +
  取消星标缓存一致（现有 invalidate 前缀失效已覆盖）。

## 路线修订计划（本 Spec 批准后执行文档修订）

```text
0001–0010  已完成历史，编号不变
0011       Mobile UI Navigation & Five-Screen Alignment（本 Spec，替换原 0011）
0012       Reader Style Deep Customization（原 0011 顺延）
0013       Unified Subscription Center（原 0012）
0014       Source Discovery & RSSHub Integration（原 0013）
0015       AI Foundation & Summary（原 0014，AI Summary 第三次顺延）
0016       Translation & AI Conversation（原 0015）
0017       Reader Power UX & Unified Settings（原 0016）
0018       Production & Operations（原 0017）
0019       MVP Stabilization & Release（原 0018）
（可选 0011a Basic Global Search：若用户批准搜索 BFF 契约再插入）
```

## Acceptance Criteria

- AC1 四个一级 tab（首页/订阅/搜索/收藏）状态转换正确，active 状态不只靠颜色，`aria-current="page"`；
- AC2 设置不在底栏；移动抽屉与桌面侧栏的品牌区右上角均可打开设置（Modal / 全屏页按现有响应式壳）；
- AC3 RSS 根节点新会话默认收起；展开/收起有 aria-expanded/aria-controls/chevron；loading/error/retry 在折叠结构内正常；
- AC4 侧边栏/订阅页选 feed 后切回首页、更新 scope、关闭移动抽屉；
- AC5 收藏页复用 starred 服务端查询（无数据复制）；取消星标后列表与缓存一致；
- AC6 Reader 打开隐藏底栏，返回恢复此前 section/筛选/滚动状态；
- AC7 抽屉支持 Escape/遮罩/导航关闭，打开时锁定背景滚动，关闭后焦点恢复到触发按钮；
- AC8 五页面在 360/390/430/768 视口无横向 overflow，底栏不遮挡最后一条内容，标题真正居中；
- AC9 所有图标按钮有 accessible name；键盘可完成开抽屉/切 tab/展开 RSS/打开设置/返回 Reader；
- AC10 loading/empty/error/长标题/无图降级状态齐全；不出现伪造的分类、未读数、结果数、热点；
- AC11 订阅页 CRUD 动作禁用 + `0012` 徽标；搜索页诚实呈现"全局搜索尚未接入"；
- AC12 Playground 新增五场景 fixture（确定性数据，与生产 API 类型分离，不进生产入口）；
- AC13 BFF 零改动、既有测试全绿、0009/0010 行为无回归（含 j/k/u/s 快捷键、分栏持久化、主题）。

## Tasks（Build 顺序，批准后严格逐步执行，每步完成立即验证）

1. Gate 1：AppSection store + MobileTabBar 四入口 + MobilePageHeader + SidebarHeader 设置入口 + 导航测试；
2. Gate 2：SourceTree disclosure + 工作区去重 + 抽屉 scroll lock/焦点恢复 + 响应式/a11y 测试；
3. Gate 3：EntryCard + 首页卡片化 + FavoritesPage（复用 starred）；
4. Gate 4：SubscriptionsPage + SearchPage（历史 + 诚实空态）；
5. Gate 5：Playground fixtures + 七视口截图矩阵 + 集中 polish + 复核；
6. Gate 6：全量回归 + 文档同步 + 交付报告。

## Verification

```bash
cd apps/web && pnpm test && pnpm lint && pnpm build
# Gate 5 追加：Playwright 真实浏览器截图（本机 chromium，见 docs 截图矩阵记录）
```

每个 Gate 报告必须附：刚运行的命令、退出码、测试数量、失败详情（不得沿用旧报告）。

## Documentation updates（Gate 6 执行，路线修订在批准后先行）

- ROADMAP.md：总览/正文/依赖图/变更记录（0011 替换 + 0012–0019 顺延，保留追溯说明）；
- PROJECT_STATE.md：当前里程碑、已知缺口、编号引用；
- README.md / AGENTS.md：current milestone 与响应式规则引用；
- 新增 devlog/0011-mobile-ui-five-screen-alignment.md；
- PRD/ARCHITECTURE 仅在产品范围/架构决策变化时更新（本 Spec 预计不动）。

## Risks / Unknowns

- R1 抽屉升级为完整 modal/focus trap（用户已批准）：基于 Sheet primitive 增强，需满足 WAI focus 要求（trap、初始焦点、关闭后焦点恢复）；
- R2 EntryCard 移动端与桌面 EntryRow 共存：Timeline 桌面行保持 0009 密度，卡片仅移动端启用（max-lg）；
- R3 768–1023px 保持现有 Drawer + list/detail，不出现底栏（用户已确认，避免第三种导航形态）；
- R4 无分类契约下"未分组"分组几乎等价于平铺——Gate 2 按单一未分组 disclosure 实现，未来分类契约到位后扩展。

## 与用户决策的对应关系（2026-08-30 批准）

1. 抽屉升级为完整 modal/focus trap（复用/增强 Sheet primitive，满足 WAI focus 要求）；
2. 搜索策略：默认"诚实空态 + 0011a Basic Global Search 候选"，本 Spec 不实现搜索 BFF 契约；
3. `.gitignore` 增加 `*.zip` 规则，任务包不入库；
4. "未读"入口做成时间线下的过滤子项（与现有 view='unread' 语义一致）；
5. 768–1023px 保持现有 Drawer + list/detail，不出现底栏（仅 <768 显示导航岛）。

---

## Appendix — Reference Matrix

> 参考图对照矩阵。优先级：交互语义与信息架构 > 视觉层级与节奏 > 响应式关系 > 精确像素。
> 原则：参考图是设计意图，不是复刻对象——不复制状态栏/9:41/固定 390px/示例数据/第三方资产。

| 页面/区域 | 参考图意图 | 当前实现 | 真实数据来源 | 目标组件 | 响应式规则 | 允许偏差 | 验证证据 |
|---|---|---|---|---|---|---|---|
| 侧边栏-品牌区 | LumiRSS + 流光阅源 副标题；右上角圆形设置按钮 | 品牌区只有标题+副标题，设置在侧栏底部整行按钮 | — | SidebarHeader（Gate 1 已实现） | 同一组件用于移动抽屉与桌面侧栏 | 设置图标样式细节 | Gate 1 浏览器截图 ✓（390 抽屉 + 1440 桌面） |
| 侧边栏-全部信息流 | 独立选中项，高亮背景 | 已实现（NavItem active） | view=all+selectedFeedUrl=null | 保留 | — | — | 既有测试 |
| 侧边栏-RSS 根节点 | disclosure 可折叠（默认收起），右侧计数 | 平铺：点击“RSS 订阅”无折叠语义，feeds 永久摊开 | useFeeds（无分类字段） | RssDisclosure（Gate 1 已实现，默认收起） | 默认收起，每会话重置 | 无分类契约→只显示“未分组”组，不显示设计/AI 等假分类 | Gate 1 浏览器验证 ✓（aria-expanded + 展开列 4 真实 feed） |
| 侧边栏-分类分组 | 柔彩文件夹 + 分类名 + feed 数 + 展开箭头 | 无（Feed 契约仅 title/feedUrl） | 无契约 | 不实现（诚实降级为未分组） | — | 整块区域允许偏差（契约缺口，记录给 0013+） | Gate 1 ✓（仅未分组） |
| 侧边栏-Phase 2 项 | 可见 + Phase 2 徽标 | 已实现（PlannedItem） | — | 保留 | — | — | 既有测试 |
| 侧边栏-工作区 | 简洁入口：时间线/收藏 | “ME 时间线 · 未读 / ME 时间线 · 收藏” 冗余标签 | view 语义 | 去重为 时间线 / 收藏（Gate 1 已实现；未读为过滤子项） | — | 未读入口形态按现有语义最清晰方式 | Gate 1 浏览器截图 ✓ |
| 移动抽屉 | 保留右侧内容上下文、backdrop dim、圆角 | 已有（85% 宽、backdrop、Escape/✕/导航关闭） | — | MobileNavigationDrawer（Gate 2 已升级完整 modal，基于增强 Sheet） | w-[min(85vw,20rem)] + rounded-r-xl + safe-area；scroll lock + focus trap + 焦点恢复 | 具体 inset/圆角值用 Lumi token | Gate 2 浏览器验证 ✓（modal 链 4/4 + 390/768/360 无溢出） |
| 底部导航 | 悬浮圆角导航岛，四等宽 tab（首页/订阅/搜索/收藏），active 蓝色 | 贴边矩形条，三 tab（时间线/收藏/设置） | — | MobileTabBar 重构（Gate 1 已实现） | <768 显示；safe-area；≥44px | 具体圆角/阴影用 Lumi token，非复刻 | Gate 1 浏览器截图 ✓ + gate-d 测试 |
| 共用 Header | 三列 grid：菜单 / 居中页面标题 / 右侧操作 | 左对齐 LumiRSS + scope 副标题两行 | — | MobilePageHeader（Gate 1 已实现） | sticky + 滚动阴影 + safe-area | 右侧只放真实可用操作，无则占位 | Gate 1 浏览器验证 ✓（360/390 headerGrid 44/1fr/44） |
| 首页-卡片 | 来源→时间/状态→标题→摘要→分类/阅读时长→右侧缩略图 | 纯文本两行行（EntryRow） | 契约无摘要/缩略图/分类/阅读时长 | EntryCard 文本退化版（Gate 3 已实现，移动端 max-lg） | 无图自动文本布局，不留空洞 | 摘要/缩略图/分类/阅读时长全部缺失（契约缺口，不做假） | Gate 3 浏览器截图 ✓（390 卡片 + 桌面 Row 密度不变） |
| 首页-日期分组 | 今天 / 昨天 分节 | 已实现（entry-groups，0010a） | publishedAt | 保留 | — | — | 既有测试 |
| 首页-scope 标题 | 居中动态 scope + 下拉 | 左对齐副标题 | view/selectedFeedUrl | MobilePageHeader 居中（Gate 1/3 已实现，390 实测动态 scope） | 超长降级为通用标题 | 下拉切换器延后（右侧真实过滤入口替代） | Gate 3 浏览器验证 ✓（首页标题动态 scope） |
| 订阅页 | Header（菜单/订阅/+）+ 搜索订阅源 + 添加RSS/OPML/分组管理 + 分类折叠 feed 列表（favicon/说明/未读数/更多菜单） | 不存在该页面 | useFeeds（仅 title/feedUrl；无 favicon/说明/未读数） | SubscriptionsPage（Gate 4 已实现：只读列表+本地过滤+未分组折叠） | 复用 app shell | CRUD 动作禁用+0013 徽标；统一 RSS 图标；无未读数不显示 | Gate 4 浏览器截图 ✓（4 真实 feed + 过滤 + feed 导航回首页） |
| 搜索页 | 搜索框 + 范围 chips + 搜索历史 + 热门搜索 + 结果(128)/相关度 | 不存在该页面 | BFF 无 search 端点 | SearchPage（Gate 4 已实现：壳+历史+诚实空态，决策 2） | — | chips 不渲染（无契约）；热门搜索省略；结果数/相关度不显示 | Gate 4 浏览器验证 ✓（Enter 提交+历史持久化 localStorage 实测） |
| 收藏页 | Header + 搜索框 + 全部/文章/稍后读/已标星 chips + 最近收藏/更早分组 + 清空 | 不存在独立页面（starred 是 view） | useEntries('starred') | FavoritesPage（Gate 3 已实现：复用 starred 查询 + EntryCard + 最近收藏/更早分组） | 复用 EntryCard | 搜索框/chips 不渲染（无契约）；无“稍后读”不伪造；无清空 API 不显示 | Gate 3 浏览器截图 ✓（分组+星标+进入 Reader+返回） |
| 状态矩阵 | loading/empty/error/长文本/无图/dark/reduced-motion | 部分已有 | — | Playground 扩展 | dev-only | fixture 与生产 API 类型分离 | Gate 5 截图矩阵 |

### 契约缺口登记（不造假，留给后续里程碑）

| 缺口 | 影响区域 | 处理 | 归属 |
|---|---|---|---|
| Feed 无 category | 侧边栏/订阅页分组 | 仅显示真实“未分组” | 0013（订阅中心可扩展 FreshRSSControlAdapter 时评估） |
| Feed 无 favicon/描述 | 订阅页 feed 行 | 统一 RSS 图标或确定性首字母占位 | 同上 |
| Feed/列表无未读数 | 侧边栏/订阅页徽标 | 不显示数量 | 0012+ 评估 unread-count 契约 |
| EntryListItem 无摘要/缩略图/阅读时长 | 首页/收藏卡片 | 文本退化 | 未来 reader/list 增强（需用户批准 BFF 变更） |
| 无全局搜索 API | 搜索页 | 页面壳 + 诚实空态；可选 0011a | 0011a（若批准） |
