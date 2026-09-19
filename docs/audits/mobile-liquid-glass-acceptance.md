# 验收记录 — 移动端专项修复 + 30 项真实新增功能（2026-09-18/19）

> 状态：**已完成（自动化验收全绿；真机/平台能力项如实标注待验证）**。
> 基线：main @ e354dc5；全部改动保留在工作区未提交（无 commit/push/部署）。
> 结论先行：三组指定修复完成；F01–F30 净新增 30 项全部有真实入口 + 行为 +
> 自动化测试证据；另有 R03/R05 附加实现（不计入 30 项）；候补 R01/R02/R04/R06 未启用。

## 0. 去重结论（F01–F30 现状核对）

逐项以「入口+实现+测试」三要素核对基线：**F01–F30 在基线版本全部无等价实现**，
仅四项"部分等价"（目标范围不重叠，仍按净新增计）：

- F12：已有 timelineCollapsed / sidebarCollapsed（单列折叠），无一键专注模式 → 净新增。
- F22：已有工作区研究包 / 书签批量导出（域级），无单篇文章导出 → 净新增。
- F23：已有 `@media print` CSS，无应用内打印入口 → 净新增入口+样式收口。
- F25：已有阅读位置自动恢复，无显式"回到顶部/返回刚才位置"按钮 → 净新增控件。

F20（正文锚定批注）与既有笔记（书签自由文本 note + 条目反链）正交，净新增。
**结论：无需候补替换；R03（来源别名）/ R05（行辅助线）为附加交付。**

## 1. P0-1 修复 — 状态更新缓存形状冲突

**用户错误**：「状态更新失败：undefined is not an object (evaluating 'n.pages.map')」

**根因**（已在当前版本复现证实）：`useEntryStateMutation.onSuccess` 按
`['search']` 裸前缀枚举缓存，保存视图清单查询（普通 query，`{items:[…]}`）
被误当 InfiniteData 调 `data.pages.map`。BFF 已 204 写入成功，前端成功回调
抛 TypeError → mutation 误入 error 态 → 误报「状态更新失败」。

**修复**：query key 分层——`SEARCH_RESULTS_KEY = ['search','results']`（分页
结果）与 `['search','saved-views']`（保存视图）；`useSearch`/`searchFiltersOf`
（key[2] 解析）/EntryActionButtons 书签标题扫描全部同步收口。

**验证**：
- 失败回归（修复前红→修复后绿）：`search-cache-shape.test.tsx` 3 用例
  （分页+视图并存 mutation 成功且视图缓存原样 / unread 过滤移除+游标保留 /
  真实 useSearch 补丁后 fetchNextPage 续页）；
- 全量 980/980（含 query-memory / search-dual-cursor 既有回归）。
- **通过（单元+组件级）**；真机待验证见 §7。

## 2. P0-2 修复 — 正文读到底自动已读

与既有「列表划过标读」（scrollMarkUnread）、「阅读位置保存」（reading-position）
严格区分，为第三个独立行为。

**实现**（lib/finish-read.ts + Reader 集成）：
- 哨兵 IntersectionObserver 以 Reader 滚动容器为 root（不混用 window），
  挂在实际正文结束处（AI 对话面板之前）；
- 触发条件（起点与触发点各核验一次）：开关开 + 未读 + 未被暂停 + 末尾稳定
  可见 + 页面前台 + 主动向下推进 ≥40px（微小余量按余量一半、至少 8px）+
  停留 ≥1000ms；
- 程序性豁免：恢复位置/自动滚屏/回顶恢复前调 noteProgrammaticScroll()
  （200ms 窗口，自动滚屏每帧续期——F18 测试证明滚屏期间零 PATCH）；
  上滑不累计；图片/译文重排后每次滚动重测滚动余量；
- 失败释放可重试（不进永久已处理集合）+ 可理解提示 + 重试按钮；
- 手动未读 → 会话级暂停；切文章/后台/卸载取消判定；一次意图只发一次；
- 短文（余量 ≤24px）不自动判定 → 「读完了」显式按钮；
- 设置 `readerAutoMarkRead`（portable，默认开；旧文档缺键→默认值，阅读
  行为组有开关与解释文案）。

**阈值（写入测试）**：DWELL 1000ms / 推进 40px / 豁免 200ms / 短文 24px。

**验证**：`finish-read.test.tsx` 15 用例（状态机全矩阵）+ `finish-read-reader.test.tsx`
4 用例（哨兵位置契约 / 滚动+停留→恰好一次 PATCH {read:true}+detail 缓存翻转
零重拉 / 短文按钮 / 开关关闭零派发）。**通过（单元+组件级）**。

## 3. P1 — iPhone 比例 / Liquid Glass / 侧滑返回

### 3.1 布局
viewport-fit=cover、`--safe-*` 全套、h-dvh、底栏 safe-area padding 均核对就位；
触控 ≥44px 延续；旅程覆盖 320/375/390/430（+平板/桌面为既有 projects）。
无整页横向溢出断言（G1/G7）。**通过（自动化）；真机待验证。**

### 3.2 Liquid Glass
`.lumi-glass` 材质层（index.css）：半透明着色表面 + backdrop-filter(18px,
saturate 1.5) + 上缘高光 + 柔和阴影；`@supports` 完整不透明回退；
`prefers-reduced-transparency` 自动降级；深色高光减弱。作用域：底部导航岛、
移动顶栏、底部 sheet——**正文与长列表保持稳定底色**。设置 `glassEffect:
auto|on|off`（portable，默认 auto；off=完整不透明不损坏）。旅程 G4 断言
data-glass 切换。**通过；Safari 真机模糊观感/帧率待验证。**
（Web 实现，非 Apple 原生材质 API。）

### 3.3 统一返回链
- `lib/nav-history.ts`：最小历史层（影子栈同步恢复 + popstate 幂等；重复
  导航不 push；浮层按层级参与——一次后退只关一层；根守卫不执行 back；
  initNavHistory 在 App 挂载一次）；
- 顶栏返回 / 浏览器后退/前进 / 边缘侧滑共用 goBack()；
- 搜索词/筛选提升 `store/search-state.ts`；列表滚动锚点 `lib/list-anchor.ts`；
- 边缘侧滑 `lib/edge-swipe.tsx`：左缘 ≤20px 起点、横向意图（dx>12 且
  |dx|>|dy|×1.5）、提交（≥96px 或 ≥0.5px/ms）、预览 0.35×上限 120px、
  减少动态效果跳过动画；不全局 preventDefault / 不改 touch-action；
  touchcancel/手势中 popstate（原生返回接管）即放弃防双跳；
- 设置 `swipeBackGesture`（默认开）。
- 阈值为本项目设计值，非 Apple 标准。**nav-history.test 10 用例 +
  旅程 G2/G3 通过；真机手势表现待验证（§7）。**

## 4. P2 — 全部文档卡片/列表项显示标题和真实来源

- BFF：`EntryListItem` +feedUrl（标题→订阅 URL 映射，TTL 缓存，解析不到
  None=不可点击的诚实降级）/ +snippet（html_to_text ≤160 字纯文本）/ +
  coverUrl（首个 http(s) img src；data:/相对路径拒绝）；`EntryDetail` +feedUrl；
  read-later 投影行补 feedUrl。既有契约有意迁移点：列表 DTO 现含有界摘要
  （≤160 字纯文本，正文仍绝不下发——test_list_entries_never_returns_body
  迁移并强化）；列表请求流多一次只读 subscription/list（TTL 缓存）。
- Web 统一 `[来源图标][来源名 · 时间]`：`lib/source-meta.tsx`（SourceGlyph
  首字符中性方块——零网络零隐私外发；SourceLabel 有 feedUrl→点击进入该
  订阅范围、无→纯文本不伪装按钮；resolveSourceName 空白→「来源未知」）；
  接入 EntryCard/EntryRow/SearchPage 结果行/ReaderHeader 元信息行/
  UnifiedContentCard。
- 验证：`list-display.test.tsx` 10 用例 + BFF `test_entry_adapter` enrich
  用例（映射命中/未命中 None/订阅清单失败 fail-open/截断/协议过滤）。
  **通过。**

## 5. F01–F30 逐项验收（30/30 净新增）

| ID | 功能/入口 | 存储 | 测试证据 | 状态 |
|---|---|---|---|---|
| F01 | 设置→通用→列表密度（紧凑/标准/舒适） | P | list-display（data-density 映射；触控不缩小） | ✅ |
| F02 | 设置→通用→显示摘要 | P | list-display（行渲染/消失/无字段不渲染） | ✅ |
| F03 | 设置→通用→显示封面 | P | list-display（关=零 img；开=lazy+no-referrer） | ✅ |
| F04 | 设置→通用→时间显示（相对/绝对） | P | list-display（formatRelativeTime 边界） | ✅ |
| F05 | 列表→按来源分组（折叠/只看此来源/已加载计数） | P+S | list-features（分组/折叠/计数/无 feedUrl 禁用） | ✅ |
| F06 | 列表头→最新/最早优先 | P | list-features（reverse+诚实标注"已加载范围内"） | ✅ |
| F07 | 列表→多选→批量已读/收藏/稍后读（上限100/失败重试） | S+R | list-features（逐条 PATCH 断言/部分失败重试只重发失败项） | ✅ |
| F08 | 卡片滑动动作（设置四档；左缘24px让给返回） | P+R | card-swipe（纯函数4例+接线5例：PATCH/POST 断言） | ✅ |
| F09 | 列表顶部下拉刷新列表（refetch 一次；不触上游） | S | list-features（阈值/状态文案/失败保留） | ✅ |
| F10 | 抽屉→最近阅读（30条LRU/开关/清空/不标已读） | D | recent-reads 11 例 | ✅ |
| F11 | Reader 顶部阅读进度条 | P | reader-features F11 + reader-tools | ✅ |
| F12 | Aa 面板→专注阅读（隐藏辅助；退出恢复） | S | reader-features（reader-focus 纯逻辑+接线） | ✅ |
| F13 | 工具栏→文内查找（n/m 命中/循环/无残留；CSS.highlights 降级） | S | reader-tools ArticleFindBar ×6 | ✅ |
| F14 | 正文图片→大图（缩放/平移/切换/Esc 焦点返回；hidden 模式不偷载） | S | reader-features F14 ×2 + Lightbox ×6 | ✅ |
| F15 | Aa 面板→代码自动换行（复制结果不变） | P | reader-features F15（data-code-wrap 切换） | ✅ |
| F16 | 宽表格→展开查看（语义表头；Esc 还原滚动） | S | reader-features F16 ×2 | ✅ |
| F17 | Aa 面板→按屏翻页（±90% 视口；边界 disabled） | P | reader-features F17 ×2 | ✅ |
| F18 | 更多菜单→自动滚屏（三档/暂停/停止；零 PATCH 证明不触发自动已读） | D+S | reader-features F18 ×2 | ✅ |
| F19 | 工具栏→朗读（能力检测诚实禁用；语速/暂停/切文停止） | D+S | reader-features F19 ×4（mock 接线） | ✅ |
| F20 | 选区→高亮/批注（三色/备注/跳回/删除；锚点失效诚实；设备本地） | M→D* | annotations 16 例；Reader 已挂载 | ✅ |
| F21 | 工具栏→分享（share/AbortError 静默/回退复制） | S | reader-features F21 ×4（mock 接线） | ✅ |
| F22 | 更多菜单→导出 .md/.html（标题/来源/日期/链接；剥 script） | S | reader-features F22 + reader-export ×5 | ✅ |
| F23 | 工具栏→打印（print CSS 收口 + @page） | S | reader-features F23 | ✅ |
| F24 | 更多菜单→复制引用（纯文本/Markdown；失败降级文本框） | S | reader-features F24 ×3 | ✅ |
| F25 | Reader 悬浮→回到顶部/返回刚才位置（豁免程序滚动） | S | reader-features F25 ×2 | ✅ |
| F26 | 订阅页→置顶/上移/下移（localStorage 持久） | D* | list-features（置顶/排序/边界/重挂载保持） | ✅ |
| F27 | 搜索→日期范围（快捷+自定义；chips 清除真实重拉） | S | search-features（from/to URL 断言） | ✅ |
| F28 | 搜索结果突出匹配词（mark 包裹；开关控制；零残留） | P | search-features（+gate4 断言迁移为跨 mark 匹配） | ✅ |
| F29 | 搜索→高级条件（仅标题/精确短语/排除词 chips） | S | search-features + BFF test_search_advanced 6 例（真实投影 200/400 冒烟） | ✅ |
| F30 | Ctrl/⌘+K + 抽屉按钮→命令面板（导航/视图/外观/返回；复用既有 action） | S | command-palette 10 例 | ✅ |

存储代号说明：\*F20/F26 按任务允许的 D（设备本地）实现——任务表格标注
F20=M、F26=M，实际以 localStorage 承载（BFF 无对应端点；未谎称同步；
不写回只读 Vault；不改上游订阅）。**此项与任务存储代号存在偏差，如实说明**：
如需服务端持久化（M），需新增 BFF 端点+迁移，建议后续里程碑处理。

附加（不计 30 项）：R03 来源别名（settings→订阅与来源；9 例）、
R05 阅读行辅助线（正文右上角开关；7 例）。

## 6. 命令与结果

```
apps/web:  pnpm test            → 93 files / 980 tests 全过（exit 0）
           pnpm lint            → 0 errors（warnings 为既有风格类）
           pnpm build           → ✓ built（tsc -b 全量类型检查通过）
           pnpm settings:generate / api:generate → 生成物确定性再生
services/bff: uv run pytest tests/ -q → 1078 passed, 1 skipped
              uv run ruff check src tests scripts → All checks passed
Playwright: LUMIRSS_CI_STATIC=1 LUMIRSS_E2E_BASE_URL=http://127.0.0.1:4173
            pnpm exec playwright test --project=webkit-mobile-390
              e2e/mobile-liquid-glass.spec.ts → 3 passed / 4 skipped*
            --project=mobile-390（Chromium 对照）→ 3 passed / 4 skipped*
            --project=webkit-mobile-390 e2e/ci-smoke.spec.ts → 2 passed
```
\* 跳过的 4 项（G2/G3/G5/G6）为数据依赖旅程，在静态降级模式按设计自跳
（不伪造数据）；需全栈 journey 环境执行。

本地真实服务冒烟：BFF 以源码启动（uvicorn :8787）→ `/api/v1/settings`
含全部新键且 PATCH 往返正确；`/api/v1/search?intitle=…&exclude=…` 在真实
投影命中 200、非法参数 400。

## 7. 环境阻塞与真机待验证（诚实边界）

**环境阻塞（本轮未跑，非功能缺失）**：
1. 全栈数据旅程（G2/G3/G5/G6 与既有 M1/M2）：需要 boot e2e compose 栈
   （docker-compose.prod；本机 80 端口被系统 nginx 占用，且栈镜像需本地
   重建以包含本轮 BFF 改动）。ROADMAP 亦将"boot e2e compose 栈"列为
   CI 待办。命令：`docker compose -f docker-compose.prod.yml up -d` 后
   `LUMIRSS_E2E_BASE_URL=http://127.0.0.1 pnpm test:e2e --project=webkit-mobile-390`。
2. WebKit 系统依赖已在用户授权下安装（libgtk-4/gstreamer/flite/webp/
   libavif 等）；浏览器可启动并完成上述静态旅程。

**真机待验证（自动化不能代替）**：
1. iPhone Safari：侧滑返回与原生边缘手势共存（不双跳）；
2. iPhone Safari/PWA：玻璃 backdrop-filter 观感与滚动帧率；安全区（刘海/横屏）；
3. 软键盘弹出、200% 文字缩放；
4. 朗读（speechSynthesis 中文声）实际听感；Web Share 系统面板；
5. 打印对话框实际输出（PDF 保存为系统能力，未承诺）。

语音/分享/打印/选区等平台能力均为 **mock 接线验证**（证明调用链正确），
不单独证明系统能力真实可用。

## 8. 变更范围与回滚

- **BFF**（7 文件 + 生成物）：models.py、adapters/freshrss.py（enrich+
  TTL feedUrl 映射）、search_store.py / search_index.py / routers/search.py
  （F29 高级条件：绑定参数 SQL，无字符串拼接）、routers/entries.py 无改、
  routers/workspaces.py（read-later feedUrl）、app_settings.py（15 个新
  portable 键）、scripts/export_settings_meta.py（枚举改由模型 Literal
  自动推导，防漂移）、gpt_digest.py / lumi_data_export.py（仅 ruff 存量
  修复：未用变量/循环变量）。
- **Web**：api/queries.ts（search key 分层）、store/{reader-ui（导航 push）,
  search-state（新）, app-settings（15 新键归一化）}、lib/{finish-read,
  nav-history, edge-swipe, list-anchor, source-meta, reader-tools,
  reader-find, reader-speech, reader-export, reader-focus, annotations,
  source-aliases, recent-reads, card-swipe, search-advanced, highlight-text,
  command-registry, date-format（相对时间）}（均新/增量）、components/（Reader
  ReaderHeader ArticleContent ArticleLightbox ReaderProgress ArticleFindBar
  AnnotationsLayer AnnotationPopover ReadingRuler EntryList EntryCard
  EntryRow UnifiedContentCard SearchPage SubscriptionsPage CommandPalette
  RecentReads MobileHeader MobileTabBar MobilePageHeader MobileNavigationDrawer
  ShortcutsHelpDialog 无改、settings/categories、ui/Sheet、SourceAliasSettings）、
  index.css（密度/玻璃/打印/专注）、keyboard-shortcuts.ts（Ctrl/⌘+K）、
  playwright.config.ts（webkit-mobile-390 project）、e2e/mobile-liquid-glass.spec.ts。
- **生成物**：settings-meta.ts、openapi.json、schema.ts——生成器可再生；
  `pnpm settings:check && pnpm api:check` 验证一致性。
- **迁移**：无数据库 schema 迁移（portable settings JSON 文档向后兼容，
  旧文档缺新键→默认值）；localStorage 新键独立可删；无破坏性变更。
- **回滚**：任务全程未提交；`git status` 即完整清单，`git checkout -- <path>`
  逐文件回退；生成物用生成器再生。
- **工作区异常**：会话中途 `.qoder/plans/Progress_Board_Spec_e0e2c1c2.md`
  被外部删除（非本任务操作），已按"保留用户工作"原则从 HEAD 还原。
- **安全说明**：Mimosa 本轮标记的 1 项 SSRF 位于 Playwright 自动生成的
  trace viewer 报告产物（gitignored，非本项目源码、非服务端请求路径）——
  误报，生成目录已清理；本轮未新增任何按用户 URL 发起服务端请求的代码。
