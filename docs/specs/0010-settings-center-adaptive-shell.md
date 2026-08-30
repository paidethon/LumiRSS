# Spec 0010 — Settings Center & Adaptive Shell

> 日期：2026-08-29
> 对应 PRD 阶段：Phase 6 — Lumi-native Product Shell（v6.0 路线修订后）
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**
> 批准前唯一允许写入的文件是本 Spec。
>
> 前置：0009 UI Reboot & Reference Lab 已完成并经 PR #15 合入 main
>（main @ 6686eea）。0010 分支基于该 main 创建。

## Goal

把 LumiRSS 从"能设置主题"升级为**完整的设置中心 + 自适应外壳**，全部
纯前端实现（**BFF 继续零变化**）：

```text
Folo 式设置 Modal（左导航 + 右内容，声明式设置行）
    ↓
9 大分类：5 个真实可用（通用/外观/阅读与快捷键/数据控制/关于）
          4 个 planned（订阅与来源/AI/账户与服务/工作区）
    ↓
左侧栏信息架构分组（信息来源 / 工作区，Phase 2 项可见但禁用）
    ↓
三栏可拖拽调宽 + 可折叠 + 状态持久化
    ↓
移动端 Folo 化：底部 Tab 导航 + 全屏设置页
    ↓
进度看板样式与 LumiRSS 主站统一（内容 + 视觉双修订）
```

最终必须证明的结论：

> 设置中心里每一个可交互的控件都**真实生效并持久化**；每一个未实现的
> 功能都**明确标注 planned 与归属里程碑**；BFF 一行代码没改；0009 的
> 全部行为测试仍然通过。

0010 与 0009 的本质区别：

```text
0009  重建视觉体系（tokens/primitives/三栏观感）——表现层地基
0010  重建产品外壳（设置中心/导航架构/自适应分栏/移动导航）——产品骨架
```

一个合格的 0010 最终 Diff 形态：

```text
apps/web/src/components/settings/     ← 新增：设置中心（Modal + 各分类页）
apps/web/src/components/ui/           ← 扩展：SettingsModal、Separator 等
apps/web/src/store/app-settings.ts    ← 新增：类型化设置 store（localStorage）
apps/web/src/components/Sidebar.tsx   ← 信息架构分组改造
apps/web/src/components/App.tsx       ← 分栏拖拽/折叠接线
apps/web/src/components/Mobile*.tsx   ← 底部 Tab 导航改造
apps/web/src/__tests__/               ← 新增测试
services/bff/                         ← 整个目录 0 文件变化
docs/PRD.md / ROADMAP.md /            ← 路线修订（见本 Spec §修订计划）
docs/PROJECT_STATE.md / project-data.js / docs/progress/index.html
                                      ← 路线修订 + 看板样式统一
```

## 前置条件核对（Spec 阶段已真实核验，2026-08-29）

### 分支基线（已验证）

```text
基线分支：main @ 6686eea（Merge PR #15 — 0009 全部交付物已合入）
工作分支：feat/0010-settings-center-adaptive-shell（用户批准创建）
UI 参考：Folo 实机（app.folo.is，用户已登录可对照）+ 用户提供的
          设置界面/侧栏参考图（~/projects/LumiRSS-reference/
          screenshots/user-provided/）+ 本地克隆仓库源码；
          实现时禁止凭空设计——每个界面/交互必须在参考图或源码中
          有对照依据，无对照的新设计需在 Gate 验证时说明来源。
```

### 0009 交付的可复用地基（已验证，非旧记忆）

- Lumi Mist tokens/themes（`styles/tokens.css` / `themes.css`）；
- 11 个 primitives（Dialog 含遮罩点击关闭 + Escape + focus trap——
  设置 Modal 直接复用，"点空白退出"零新代码）；
- 主题三态 store（`store/theme.ts` + localStorage）——迁移进新 app-settings store；
- Reader 背景钩子（`lib/reader-bg.ts` + `data-reader` 变体）——同上迁移；
- Sidebar 分类色圆点 / Timeline 两级行 / Reader 工具栏——保持不动。

### 参考实现研究结论（已读源码，2026-08-29）

**Folo**（`modules/settings/`，SHA 78f6bd1b）：
- Modal 架构：`SettingModalContent`（tab 状态 context）+ `SettingModalLayout`
  （950×800 可调尺寸，Resizable + 拖拽）+ 左导航 + 右内容；
- **声明式 setting-builder**：`{type:"title"} | {key,label,description,onChange}`
  按值类型自动映射 Switch/Select/Input + ActionItem——一个 builder 渲染
  全部分类页，代码量极小；
- 分类页 13 个（general/appearance/ai/plan/integration/spotlight/
  data-control/shortcuts/notifications/lists/feeds/profile/about）。

**OrigRead-Desktop**（`SettingsPanel.tsx` + `shared/settings.ts`，SHA 8b59bcb4）：
- 类型化设置模型 `DesktopSettings`（单一 interface + Patch 局部更新）；
- **Reader 排版矩阵**：字号 15/17/19/21、行高 1.65/1.85/2.05、宽度
  680/760/900、背景 theme/paper/warm/sepia/mint/custom——直接借鉴；
- **分栏约束模型**：`SOURCE_PANE_WIDTH_MIN=220/MAX=320`、
  `ARTICLE_PANE_WIDTH_MIN=320/MAX=480` + collapsed 布尔 + 持久化——直接借鉴。

**借鉴级别**：全部 inspired（研究结构与行为、独立实现、Lumi token 化），
SOURCE_MAP 登记；零行代码复制（Folo 用 jotai/motion/re-resizable 等本项目
没有的依赖，照抄反而是错的）。

## Context — 概念解释（写给初学者）

### 为什么设置用 Modal 而不是独立页面

Folo 同款：设置是"覆盖在主界面上的临时态"，左导航 + 右内容一屏内完成，
不离开阅读上下文。移动端则反过来——屏幕小，Modal 装不下，改为全屏
页面（Folo 移动端同款策略）。

### 声明式设置行（setting-builder 模式）

不手写每行 JSX，而是描述数据：

```ts
{ type: 'title', value: '自动化' }
{ key: 'sidebarHideRead', label: '隐藏已读',
  description: '在订阅列表中隐藏没有未读条目的订阅' }  // boolean → Switch
{ key: 'readerFontSize', label: '正文字号' }            // 枚举 → Select
```

一个 `<SettingItem>` 渲染器按值的 TypeScript 类型自动选控件。好处：
新增设置 = 加一行数据；所有行视觉天然一致。

### localStorage 单 key JSON 持久化

所有客户端设置合并存一个 key（`lumirss-settings`），zustand store 负责
读写。0014 加服务端 `GET/PATCH /api/v1/settings`（SQLite）时：首次
登录把 localStorage 上传合并，之后以服务端为准，localStorage 退役——
与主题持久化同一迁移模式。

### 三栏拖拽为什么不直接用 CSS Grid

Grid 的 `240px 400px 1fr` 是静态的；拖拽需要 JS 读 pointer 位移算出
新宽度。方案：Grid → flex + 显式 px 宽度（store 管理 + clamp 约束），
折叠 = 宽度置 0/48px + 记忆原宽度。分隔条是 `role="separator"`
（aria-valuenow/min/max），键盘 ←/→ 可微调（Folo 实测同款语义）。

### 移动端底部 Tab（Folo 同款）

<768px 时底部 [时间线|收藏|设置] 三 Tab（≥44px 触摸目标）；Drawer 导航
保留（☰ 入口承载信息来源/工作区分组）。手机上"底部拇指可达"优于
"顶部 hamburger"——Folo 移动端验证过的模式。

### 看板样式统一是什么意思

`docs/progress/index.html` 目前是独立的旧配色（--bg:#f7f7f4 等，与主站
Lumi Mist 无关）。统一 = 看板用自己的内联 Lumi Mist 变量副本（看板是
零依赖单文件，不能 import 主站 CSS——见看板技术约束）复制 token 值，
视觉上与主站同一家族：同一套 canvas/surface/accent/圆角/字体栈 +
Dark 模式跟随 `prefers-color-scheme`。

## Scope（只做这些，按 Gate 划分）

### Gate A — 设置中心框架

1. `store/app-settings.ts`：类型化 `AppSettings` interface + zustand
   store + localStorage 单 key 读写 + 迁移（theme/reader-bg 旧 key 数据
   并入，旧 key 保留读取兼容一个版本）；
2. `components/settings/`：SettingsModal（基于 Dialog primitive 扩展：
   左导航 + 右内容区 + 顶部标题/关闭）、`SettingItem` 声明式渲染器
   （title/boolean→Switch/枚举→Select/Action→Button）；
3. 迁移：外观设置（主题模式/阅读背景）从 SettingsDialog 旧组件迁入新
   设置中心；旧 SettingsDialog.tsx 删除（Sidebar 入口改指向新 Modal）；
4. **点击空白退出**：Dialog primitive 已有遮罩点击关闭 + Escape——验收
   即可，零新代码。

### Gate B — 分类页与真实接线

5. **通用**（真实）：界面语言（仅 zh-CN 可选，English 标注 planned）；
   侧栏隐藏已读（接线 Sidebar 渲染过滤）；时间线未读圆点开关；
6. **外观**（真实）：主题模式、阅读背景 + **Reader 排版矩阵接线**——
   字号 15/17/19/21 → `--lumi-reader-font-size`、行高 1.65/1.85/2.05 →
   `--lumi-reader-line-height`、宽度 680/760/900 → article max-width，
   CSS 变量由 store 挂载（Reader 立即响应）；
7. **阅读与快捷键**（真实）：只读速查表 + 实现基础快捷键
   j/k（下一篇/上一篇）、u（切换未读视图）、s（收藏切换）、Escape
   （关闭浮层）——键盘事件挂在列表容器，不劫持输入框；
8. **数据控制**（部分真实）：清除本地缓存（TanStack Query clear，真实
   可用）+ OPML 导入导出（planned 0011）；
9. **关于**（真实）：版本、仓库链接、AGPL-3.0-only、THIRD_PARTY_NOTICES
   链接、参考项目致谢（Folo/OrigRead inspired）；
10. **planned 页**：订阅与来源（0011）/ AI（0013）/ 账户与服务（0011）/
    工作区（Phase 2）——完整页面结构 + 控件全部禁用 + 每项标注归属
    里程碑 + 顶部说明条（延续 0009 诚实原则）。

### Gate C — 侧栏架构与自适应分栏

11. Sidebar 信息架构分组（图 2 结构）：「信息来源」（全部信息流/RSS
    订阅=现有 feeds + Phase 2 项禁用）、「工作区」（ME 时间轴=Unread/
    Starred 视图迁入 + Agent 工作台等 Phase 2 禁用 + 设置）；
    Phase 2 项：可见但禁用 + "Phase 2" 小徽标 + tooltip；
12. 三栏拖拽调宽：flex + px 宽度 store（clamp：Sidebar 220–300、
    Timeline 360–460）、`role="separator"` 分隔条（pointer 拖拽 +
    键盘 ←/→ 微调 + 双击重置）、每栏折叠按钮（Sidebar→48px 图标条、
    Timeline→折叠记忆宽度）、宽度/折叠 localStorage 持久化、
    <1024px 自动忽略分栏状态；
13. 基础回归：分栏状态不破坏移动端流程（<1024 行为与 0009 完全一致）。

### Gate D — 移动端 Folo 化 + 看板 + 文档

14. <768px 底部 Tab 导航（时间线/收藏/设置三 Tab，≥44px）；
    Drawer 保留（☰ 承载分组导航）；设置页移动端全屏化（非 Modal）；
15. 进度看板修订：内容（0010 插入 + 后续里程碑顺延 +1 + Phase 6 更名）
    与样式（内联 Lumi Mist 变量副本 + Dark 跟随系统 + 与主站同字体栈/
    圆角/accent），零依赖约束不变；
16. 文档修订（PRD/ROADMAP/PROJECT_STATE/AGENTS/README）按 §修订计划
    执行；
17. 全量回归：测试 + lint + build + 视口矩阵（5 尺寸 × 2 主题 +
    底部 Tab + 折叠态 + 拖拽后刷新恢复）+ 真实浏览器 smoke。

## Non-goals（明确不做，做了就是 scope creep）

- 服务端设置 API / SQLite（0014）；
- 订阅管理/OPML 任何真实功能（0011）；
- AI 任何真实功能（0013）；
- FreshRSS/RSSHub 服务状态探测（0011）；
- 自定义颜色选择器（0014；阅读背景沿用 follow/sepia/warm 三档）；
- Folo 的计划/集成/Spotlight/列表/通知分类（产品特性不适用）；
- Service Worker / 离线（一如既往）;
- 新第三方依赖（拖拽用原生 pointer events，不引 re-resizable）；
- 修改 `services/bff/` 任何文件。

## 硬边界（冻结，0010 不得触碰）

1. **BFF 零变化**：`git diff -- services/bff` 为空（0009 尚未 commit，
   验收基准为"0010 Build 期间 bff 目录无新增改动"）；
2. 浏览器只访问 `/api/v1/*`；无新网络请求（设置全本地）；
3. 打开文章不自动已读；read/starred set 语义不变；
4. DOMPurify / safeExternalHttpUrl 边界不削弱；
5. 移动端 <1024 list↔reader 返回流不回退（分栏状态在移动端自动忽略）；
6. 设置控件诚实原则（AC 延续 0009）：可交互 = 真实生效；planned =
   禁用 + 标注；**不存在假保存/假成功**；
7. 上游借鉴全部 inspired 级 + SOURCE_MAP 登记；
8. 看板修订不违反零依赖约束（无 React/Tailwind/CDN/构建步骤）；
9. <768px 底部 Tab 不遮盖内容（safe-area 计入）；
10. 快捷键不劫持表单输入与屏幕阅读器按键。

## 设计规格（冻结基线）

### 设置 Modal 尺寸与结构（Folo 实测锚点）

```text
尺寸:  min(950px, 92vw) × min(800px, 86dvh)，圆角 --lumi-radius-3xl(16px)
左导航: ~200px（lucide 图标 16px + 标签 14px；选中=selected surface
        + accent 文字；与主站 Sidebar NavItem 同款三态）
右内容: 滚动区，分组 = --lumi-radius-xl(12px) 卡片 + 组内分隔线
设置行: 标签+描述居左（14px/12px，primary/secondary），控件居右；
        行高 ~56px；与 Folo/OrigRead 双参考一致
```

### AppSettings 类型化模型（借鉴 OrigRead 模式）

```ts
interface AppSettings {
  // 通用
  language: 'zh-CN'                    // 'en' planned
  sidebarHideRead: boolean
  timelineUnreadDot: boolean
  // 外观
  themeMode: 'system' | 'light' | 'dark'
  readerBackground: 'follow' | 'sepia' | 'warm'
  readerFontSize: 15 | 17 | 19 | 21
  readerLineHeight: 1.65 | 1.85 | 2.05
  readerContentWidth: 680 | 760 | 900
  // 布局（<1024 忽略）
  sidebarWidth: number                 // clamp 220–300
  sidebarCollapsed: boolean
  timelineWidth: number                // clamp 360–460
  timelineCollapsed: boolean
}
```

### 侧栏信息架构（图 2 映射定稿）

```text
信息来源                     工作区
├─ 全部信息流   可用         ├─ ME 时间线（Unread/Starred）可用
├─ RSS 订阅     可用         ├─ Agent 工作台   🔒Phase 2
├─ 网页剪藏     🔒Phase 2    ├─ RAG 索引       🔒Phase 2
├─ 网页快照     🔒Phase 2    ├─ 标签 / 图谱    🔒Phase 2
├─ API 来源     🔒Phase 2    └─ 设置           可用（开 Modal）
├─ 邮件简报     🔒Phase 2
├─ 书签        🔒Phase 2
└─ Obsidian 库  🔒Phase 2
```

### 移动端底部 Tab

```text
[时间线(List icon)] [收藏(Star)] [设置(Settings)]   高度 56px + safe-bottom
时间线/收藏 = 列表页；设置 = 全屏设置页（含返回 ←）
Drawer(☰) 保留在顶栏；Reader 打开时 Tab 栏隐藏（全屏阅读）
```

### 快捷键（基础集）

```text
j / ↓   下一篇        k / ↑   上一篇
u       切换未读视图   s       收藏切换（当前选中文章）
Escape  关闭浮层（Modal/Drawer）
```

## 路线修订计划（本 Spec 批准后随 Build 执行文档修订）

### 里程碑顺延（0010 插入，后续 +1）

| 旧编号 | 新编号 | 名称 | 变化 |
|---|---|---|---|
| — | **0010** | **Settings Center & Adaptive Shell** | **新插入**（本 Spec） |
| 0010 | 0011 | Unified Subscription Center | 顺延 |
| 0011 | 0012 | Source Discovery & RSSHub Integration | 顺延 |
| 0012 | 0013 | AI Foundation & Summary | 顺延（原 0009 AI Summary 二次顺延） |
| 0013 | 0014 | Translation & AI Conversation | 顺延 |
| 0014 | 0015 | Reader Power UX & Unified Settings | 顺延；**设置服务端 API 在此落地**（localStorage 迁移点） |
| 0015 | 0016 | Production & Operations | 顺延 |
| 0016 | 0017 | MVP Stabilization & Release | 顺延；MVP 出口标准不变 |

### 受影响文档与修订内容

| 文档 | 修订 |
|---|---|
| `docs/PRD.md` v6.0 | §12 开发路线表插入 0010、后续编号顺延；§8.5 统一设置分类对齐 9 分类定稿；版本号升 v6.1 |
| `docs/ROADMAP.md` | 里程碑表 + 依赖图 + §10 路线变更政策记录本次重排（原因：设置中心与自适应外壳是产品骨架，优先于订阅管理） |
| `docs/PROJECT_STATE.md` | 里程碑账本插入 0010（in-progress）+ 后续行顺延；测试基线更新 |
| `docs/progress/project-data.js` | phases 重构：Phase 6 = Product Shell（0009+0010）；里程碑插入与顺延；currentMilestoneId=0010 |
| `docs/progress/index.html` | **样式统一**（见 Gate D 第 15 条）：内联 Lumi Mist 变量副本（canvas/sidebar/surface/accent/分类柔彩/圆角）、字体栈对齐 `--lumi-font-sans`、Dark 模式跟随 `prefers-color-scheme` + `color-scheme`、卡片/徽标/代码字体视觉对齐主站；**零依赖约束不变**（纯内联 CSS 变量副本，不 import 主站文件） |
| `AGENTS.md` | Current milestone 更新为 0010；权威顺序补 `docs/ROADMAP.md` 位置说明 |
| `README.md` | Current status / Roadmap at a glance / Documentation 表更新 |
| `docs/specs/0009-*.md` | 不改写历史 Spec；仅在 Spec 头部加一行"后续：0010 起编号顺延"注记？——**否，历史 Spec 冻结不动**，编号语义由 ROADMAP 变更记录承载 |

## 进度看板修订详规（Gate D 第 15 条的冻结细节）

**内容修订**：

```text
1. Phase 6 更名 "Source Control" → "Product Shell"，含 0009 + 0010；
   原 Phase 6~9 各后移一位（Source Control 0011/0012、AI 0013/0014、
   Completion 0015、Production 0016/0017）
2. 插入 0010 里程碑条目（goal/短目标来自本 Spec）
3. 0009 条目补 devlog 链接（已存在，确认）
4. currentMilestoneId: 0010 → 0011 完成时再移
5. updatedAt + 维护顺序遵循双真源规则（PROJECT_STATE 先行）
```

**样式统一修订**（看板自身零依赖内联实现）：

```text
1. :root 变量组替换为 Lumi Mist Light 副本（canvas #f6f4f4 / sidebar
   #f1eeee / surface #fbfafa / accent #6d78e8 / 文本四档 / separator /
   圆角 scale / 分类柔彩 7 色）
2. @media (prefers-color-scheme: dark) 提供 Dark 副本（#18181a 系列
   + accent #8993f5）+ color-scheme: dark
3. font-family 对齐主站栈（system-ui, SN Pro, PingFang SC…）
4. 现有 CSS 类（.card/.badge/.phase 等）改引新变量——HTML 结构不动，
   只换变量定义与少量类引用（最小 diff 原则）
5. 验收：390/768/Desktop 三档无横向滚动 + Light/Dark 双主题截图
   （Playwright 模拟 colorScheme）
```

## Acceptance Criteria

| # | 验收标准 |
|---|---|
| AC1 | 分支隔离：全部工作在 feat/0010-settings-center-adaptive-shell；Gate A–D 每个结束停下等用户批准 |
| AC2 | BFF 零变化：0010 Build 期间 `services/bff/` 无任何新增改动 |
| AC3 | 设置中心结构：左导航 9 分类 + 右内容滚动 + 声明式 SettingItem 渲染器（title/boolean/枚举/Action 四型） |
| AC4 | 点击 Modal 空白遮罩 / Escape / ✕ 均关闭设置（复用 Dialog primitive 行为） |
| AC5 | 通用页真实生效：侧栏隐藏已读即时过滤 feeds 列表；未读圆点开关即时生效；语言仅 zh-CN 可选且 English 项标注 planned |
| AC6 | 外观页真实生效：主题模式/阅读背景迁移后行为不变；Reader 字号/行高/宽度三档选择即时改变 Reader 渲染并持久化（刷新恢复） |
| AC7 | 快捷键真实可用：j/k/u/s/Escape 在列表上下文生效；输入框聚焦时不劫持；速查表页只读展示 |
| AC8 | 数据控制页：清除本地缓存真实可用（Query cache 清空 + 界面回到加载态）；OPML 标注 planned 0011 |
| AC9 | 关于页真实：版本/仓库/LICENSE(AGPL-3.0-only)/THIRD_PARTY_NOTICES/参考致谢链接 |
| AC10 | planned 页（订阅/AI/账户/工作区）：完整页面结构、控件全禁用、每项标注归属里程碑、无假保存 |
| AC11 | 旧 SettingsDialog.tsx 删除，Sidebar 入口指向新设置中心；无死代码 |
| AC12 | 侧栏信息架构：信息来源/工作区两组；可用项正常导航；Phase 2 项可见但禁用 + Phase 2 徽标 + tooltip 说明 |
| AC13 | 三栏拖拽：pointer 拖拽调宽（Sidebar 220–300 / Timeline 360–460 clamp）、键盘 ←/→ 微调、双击重置、折叠/展开（Sidebar 48px 图标条）、宽度与折叠刷新恢复；<1024 自动忽略分栏状态 |
| AC14 | 分隔条 a11y：role="separator" + aria-valuenow/min/max + aria-orientation |
| AC15 | 移动端 <768px：底部 Tab（时间线/收藏/设置，≥44px + safe-bottom）；设置全屏页（含返回）；Reader 打开时 Tab 隐藏；Drawer 保留 |
| AC16 | 移动端 768–1023 行为与 0009 一致（list↔reader 返回流零回归） |
| AC17 | 设置持久化：全部真实控件刷新后恢复（localStorage 单 key）；旧 theme/reader-bg key 数据自动迁移 |
| AC18 | 视口矩阵：1920/1440/1024/820/390 × Light/Dark 零横向溢出 + 底部 Tab/折叠态/拖拽后刷新专项截图 |
| AC19 | 看板修订：内容（0010 插入 + 顺延 + Phase 6 更名）+ 样式（Lumi Mist Light/Dark 双主题 + 主站字体栈）落地；390/768/Desktop 无横向滚动；零依赖不变 |
| AC20 | 文档修订：PRD v6.1 / ROADMAP / PROJECT_STATE / AGENTS / README 与实际一致（编号顺延全链路一致） |
| AC21 | 上游溯源：settings-builder/分栏约束/底部 Tab 借鉴登记 SOURCE_MAP（inspired）；无 icons/mgc |
| AC22 | 既有测试全量通过或诚实隔离：0009 的 162 tests 适配后全绿 + 新增（settings/分栏/Tab/快捷键）全绿；lint 0 errors；build 成功 |
| AC23 | 真实浏览器 smoke：设置各分类真实控件操作 + 刷新恢复 + 分栏拖拽 + 移动 Tab 导航全程 + console 零 error + 无新网络请求（设置全本地） |
| AC24 | 无 Secret/私图入库；无新第三方依赖（0 新增 package.json 条目） |
| AC25 | Scope：Non-goals 清单零违反；无 Phase 2 真实功能 |
| AC26 | 全部 Gate 通过并经用户批准后：0010 → completed，0011 → next（不启动） |

## Tasks（Build 顺序，批准后严格逐步执行，每步完成立即验证）

### Gate A — 设置中心框架（用户批准本 Spec 后开始）

1. `store/app-settings.ts`：类型 + store + localStorage 单 key + 旧 key 迁移逻辑 + 测试；
2. `components/settings/SettingItem.tsx`：声明式渲染器四型 + 测试；
3. `components/settings/SettingsModal.tsx`：左导航 + 右内容骨架（空分类占位）+ 挂载入口替换 + 旧 SettingsDialog 删除；
4. Gate A 验证：Modal 开关/导航切换/空白退出截图 + 测试 → **停，等批准**。

### Gate B — 分类页与真实接线

5. 外观页完整接线（主题/背景迁移 + Reader 排版三档 CSS 变量挂载）+ 测试；
6. 通用页（隐藏已读/未读圆点/语言）+ Sidebar/Timeline 接线 + 测试；
7. 快捷键实现（列表容器键盘事件）+ 速查表页 + 测试；
8. 数据控制（清缓存）+ 关于页；
9. 四个 planned 页（订阅/AI/账户/工作区，禁用结构）+ 测试；
10. Gate B 验证：各分类截图 + 全部真实控件操作录验 → **停，等批准**。

### Gate C — 侧栏架构与自适应分栏

11. Sidebar 信息架构分组改造（含 Phase 2 禁用项）+ 测试；
12. App.tsx 分栏化：flex + 宽度 store + 分隔条（拖拽/键盘/双击/折叠）+ 持久化 + 测试；
13. 移动端回归确认（<1024 行为不变）；
14. Gate C 验证：拖拽/折叠/刷新恢复/键盘微调录验 + 截图 → **停，等批准**。

### Gate D — 移动端 Folo 化 + 看板 + 文档

15. <768px 底部 Tab + 设置全屏页 + Reader 时 Tab 隐藏 + 测试；
16. 看板修订（内容 + 样式统一，双真源顺序）；
17. 文档修订（PRD v6.1 / ROADMAP / PROJECT_STATE / AGENTS / README + SOURCE_MAP 登记）；
18. 全量回归 + 视口矩阵 + 真实 smoke + devlog 0010；
19. Gate D 验证：完整证据包 → **停，等最终批准**。

## Verification

```text
V1  0010 Build 期间 services/bff 无新增改动（git status/diff 检查）
V2  设置 Modal：空白遮罩点击 / Escape / ✕ 三路径关闭（Playwright 实测）
V3  真实控件逐项操作 + reload 恢复（Playwright 脚本：改字号→截图→reload→
    断言恢复；隐藏已读→断言 feeds 列表过滤；拖拽→reload→断言宽度恢复）
V4  Reader 排版三档：改字号/行高/宽度 → computed style 断言
V5  快捷键：j/k 焦点移动、u 视图切换、s 收藏切换（可逆恢复）；
    输入框聚焦时按键不劫持
V6  分隔条：拖拽 clamp 边界值 / ←→ 微调 10px / 双击重置 /
    role+aria 断言
V7  <768 底部 Tab：三 Tab 导航 + 触摸目标 ≥44px + safe-area +
    Reader 时隐藏；768–1023 与 0009 行为一致
V8  Phase 2 禁用项：可见 + disabled + 徽标 + tooltip（snapshot 断言）
V9  视口矩阵 5×2 + 专项（折叠/拖拽/Tab）截图零横向溢出零 console error
V10 看板：Light/Dark 截图 + 390/768/Desktop 无横向滚动 +
    数据结构 node 校验（无孤儿里程碑）
V11 localStorage 迁移：预置旧 theme key → 加载 → 断言并入新 store
V12 cd apps/web && pnpm test && pnpm lint && pnpm build → 全绿（真实数字）
V13 真实 smoke：完整用户旅程（设置→分栏→阅读→移动端 Tab）console 干净
V14 SOURCE_MAP 新增条目齐全；package.json 零新依赖
```

## Documentation updates（AC 全过后随 Gate D 执行）

按 §路线修订计划与 §进度看板修订详规执行；devlog 0010 新建；
PROJECT_STATE 测试基线更新为新真实数字。

## Risks / Unknowns

- **0009 已收口**：PR #15 合入 main，0010 基线干净，无叠加风险；
- **拖拽手感**：pointer events 手写实现首次调参（阈值/惯性不做，保持
  简单直给）；Gate C 录验为准；
- **底部 Tab 与现有 MobileHeader 的信息分配**：☰ 顶栏 + 底部 Tab 双导航
  在 <768 并存，信息层级需实测拿捏（必要时 Gate D 微调 ☰ 内容）；
- **看板 Dark 模式**：`prefers-color-scheme` 无手动切换（看板无 JS
  状态框架，保持零依赖简单性；主站才有手动切换）；
- **快捷键范围**：仅基础集；Folo 完整快捷键体系（数十个）不做。

## 与用户决策的对应关系（2026-08-29 确认）

| 决策 | 落实 |
|---|---|
| 新 0010 里程碑插入 | 本 Spec + §路线修订计划 |
| 允许创建分支 | feat/0010-settings-center-adaptive-shell（已建） |
| 允许修改路线 + 修订 PRD 等文档 | §路线修订计划（PRD 升 v6.1） |
| Spec 风格延续 0001–0008 | 中文 / Goal / 前置核验 / Context / 硬边界 / AC 表 / Tasks / V |
| 后续路径标出 | §路线修订计划顺延表 + ROADMAP 依赖图更新 |
| 侧栏 Phase 2 可见但禁用 | §设计规格 + AC12/V8 |
| 移动端 Folo 同款 | §设计规格底部 Tab + AC15/V7 |
| 纯 localStorage 持久化 | §Context 迁移路径 + AC17/V11（服务端 API 归 0015） |
| 看板内容 + 样式统一 | §进度看板修订详规 + AC19/V10 |
