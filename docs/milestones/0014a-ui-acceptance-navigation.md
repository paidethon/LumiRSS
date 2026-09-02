# 0014a — UI Acceptance & Navigation Consistency

> Status: **Completed** · Branch: `fix/0014a-ui-acceptance-navigation`
> Created by Gate 0 (2026-09-02) on top of `feat/0014-source-discovery-rsshub`
> (`be5f80f`). Completed by Final Gate (2026-09-02).

## Why this milestone exists

0014（Source Discovery & RSSHub Integration）通过了全部自动化测试，但
**post-implementation 人工/视觉验收**发现了若干真实 UI 接受度缺陷：

**Primary defects (A–D)**

```text
A. Desktop Web 无法轻易找到「添加来源」——添加来源入口目前位于
   移动端的订阅管理页（SubscriptionsPage），桌面浏览路径（Sidebar +
   Timeline + Reader）没有可发现入口。

B. 移动端从「收藏」选择文章后，没有进入全屏 Reader 视图：收藏列表
   section 仍然占用布局空间，与 Reader 形成垂直分屏（预期是列表 →
   全屏 Reader → back 原列表）。

C. 设置里仍存在 stale 的 FreshRSS / RSSHub “planned” 标签
   （如「账户与服务」里的 FreshRSS 状态 planned · 0013），与
   已经真实存在的 0013/0014 能力（订阅管理、OPML 导入导出、
   RSSHub 来源发现/预览）互相矛盾。

D. 0014 没有获得真正的 Playwright 实机点击验收（当时 Playwright MCP
   配置已持久化但需重启 OpenCode 才生效；0014 最终以 DOM 级测试 +
   live smoke 收口）。
```

## Goal

关闭 0014 之后发现的真实浏览器/UI 接受度缺口，并在 AI 工作开始前确立
统一的来源入口（Add Source）与文章打开（Reader）语义：

```text
Any normal article-list surface（首页/订阅列表/收藏/稍后读/未来的搜索）
        ↓ 点击文章
        full-screen mobile Reader（移动）；分栏（桌面）
        ↓ back
        回到来源列表（section / scope / view 保持不变）
```

## Scope

- Desktop/tablet/mobile 均有直观、一致的「添加来源」入口；
- 移动端所有正常文章列表 → 全屏 Reader → back 语义一致；
- 设置中 FreshRSS / RSSHub 能力标识与现实一致（01 已实现 / 0018
  运营 / 无过期重复）；
- **真实 Playwright 桌面 + 移动验收**（0014a 完成的前置条件）。

## Non-goals（本 milestone 明确不做）

- 不重设计整个应用；不引入新的路由框架；
- 不新建第二个 AddSourceDialog / 第二套订阅逻辑；
- 不创建新的复杂 FreshRSS 健康系统；
- 不实现 0018 RSSHub Control Center / FreshRSS 运营集成 / WebDAV；
- 不实现 0015 AI / Lumi SQLite 持久化；不开始 0015–0019 实现。

## Gates

```text
Gate 0 — 基线 + Spec + 分支（本文件）
Gate 1 — Desktop 添加来源可发现性（Sidebar 入口 ↔ 既有 AddSourceDialog）
Gate 2 — 移动端收藏 → 全屏 Reader（App 布局契约修复）+ 回归测试
Gate 3 — FreshRSS / RSSHub 设置界面真实性（分类 stale 标签清理）
Gate 4 — Playwright 桌面 + 移动实机验收（当前代码，无旧 dev server）
Gate 5 — 0014a 插入路线图 + 0015–0019 产品决策修订（文档）
Final — 全量测试 + lint + build + 验收矩阵 + 最终 commit
```

## Gate Progress

### Gate 0

Status: Completed (2026-09-02)

- 基线：`feat/0014-source-discovery-rsshub` @ `be5f80f`（0014 Final
  commit），working tree clean；
- 分支：`fix/0014a-ui-acceptance-navigation`；
- 0014 保持历史状态为 Completed（重编号不做；0014a 是 post-0014
  验收 follow-up milestone，保持可追溯性）。

### Gate 1 — Desktop 添加来源可发现性

Status: Completed (2026-09-02)

关键约束：**不新建第二个 AddSourceDialog、不复制订阅逻辑**；来源添加
流程保持 0014 既有链路：

```text
添加来源 ↓ RSS / Atom | 网站 | RSSHub ↓ 预览 ↓ 分类 ↓ 订阅 ↓ FreshRSS
```

Implemented:

- `Sidebar`（桌面上下文 = 未传 onNavigate）在「RSS 订阅」行尾新增
  “+” 按钮（icon-only，`aria-label="添加来源"` + `title` 工具提示；
  focus-visible 描边与既有 icon 按钮一致）→ 打开**同一个**
  `AddSourceDialog`（Sidebar 实例，桌面常驻栏内挂载；移动抽屉上下文
  不渲染——移动入口仍为订阅页「添加来源」按钮，避免 drawer 内嵌套
  对话框）；
- `SubscriptionsPage`：保留 添加来源 / 导入 OPML 并**新增 导出 OPML**
  （BFF 代理下载，浏览器不接触 FreshRSS；与设置「订阅与来源」共用
  新 hook `useOpmlExportFlow`，`SourcesSettingsSection` 同步重构）；
- Responsive 一致性：桌面（Sidebar +）／移动（订阅页按钮）／平板
  （订阅页按钮 + 抽屉）均有入口；
- 测试：`acceptance-0014a.test.tsx`（10 例：桌面入口可见／点击打开
  三模式对话框／单一 dialog／Escape 关闭重开复位／移动抽屉上下文不
  渲染／App 级唯一对话框+管理动作齐全）＋ 既有 gate4-pages 断言兼容。

### Gate 2 — 移动端 收藏 → 全屏 Reader

Status: Completed (2026-09-02)

根因：`App.tsx` 移动 section 页面（收藏/搜索/订阅）在 `selectedEntryRef`
非空时仍然渲染并占满 flex-1，与 Reader 垂直分屏——不是收藏专属 bug，
是**共享布局契约缺陷**。

Fix（共享契约，非 收藏 hack）：

- App 移动 section 页面在 Reader 打开时追加 `max-lg:hidden` 让位
  （与首页 Timeline 的 `hidden lg:flex` 同一模式：隐藏而非卸载，
  保留 DOM／导航状态）；桌面 `lg:hidden` 行为不变；
- 不变式覆盖：首页 timeline／收藏／（搜索无文章列表）／稍后读
  （view=read-later 走首页列表）任何文章点击 → 全屏 Reader → back →
  原列表，section/view/scope 不变；Reader 内动作（已读/收藏/稍后读/
  打开原文）不受影响；
- 测试：`acceptance-0014a.test.tsx` 移动收藏流 + 首页列表回归断言。

### Gate 3 — FreshRSS / RSSHub 设置界面真实性

Status: Completed (2026-09-02)

现状审计（2026-09-02）：

```text
类目                 项目                          现实
订阅与来源(IMPLEMENTED) FreshRSS 状态(实时订阅数) ✓ 真实请求结果
订阅与来源              来源发现说明(0014)         ✓
账户与服务              FreshRSS 状态 planned·0013 ✗ STALE（0013 已完成）
账户与服务              RSSHub 状态 planned·0018   △ 未来运营（描述未提 0014 现状）
备份与恢复              订阅列表(OPML) planned·0013 ✗ STALE（0013 已实现）
通用                   侧栏隐藏已读 planned·0013  ✗ STALE（0013 已完成)
```

Implemented：

- 账户与服务：删除 stale “FreshRSS 状态”副本 → 诚实二分：
  「FreshRSS 维护操作」planned·0018（描述：连接/订阅状态在
  订阅与来源实时可用；运行级维护归 0018 Production）＋「RSSHub
  运营中心」planned·0018（描述：0014 来源发现/路由目录/预览已可用；
  实例健康/诊断/配置管理归 0018 Control Center）；
- 备份与恢复：OPML 卡片改为「已实现 · 0013」＋指向订阅与来源
  的入口说明（不再谎称 planned）；
- 通用：侧栏隐藏已读不再声称 0013（无读数契约，未纳入已批准里程碑；
  徽标降为 “planned” 无编号）；
- RSSHub 设置页：文案/注释清除 stale “planned·0014”，显式区分
  「当前 0014（服务端 RSSHUB_BASE_URL + BFF 代理）／未来 0018
  Control Center（schema allow-list）」；
- 测试：更新 settings/gate-f 断言 + Gate 3 用例（账户与服务无
  planned·0013、备份页已实现标签、通用无 stale 0013）。

### Gate 4 — 真实 Playwright 验收

Status: Completed (2026-09-02)

Server 验证（无旧 dev server；全部服务从当前 0014a working tree）：

```text
5173  vite dev        — 重启自当前 tree（旧 0014 进程已终止；进程 cmd/cwd 核对）
8000  uvicorn (BFF)   — 当前代码（0014a 零 BFF 变更；health/live ok）
1200  RSSHub / 8080 FreshRSS — docker compose（0014 环境）
vite 代理 /api/v1/rsshub/routes → configured=true + 14 路由（浏览器可见面）
```

DESKTOP（1440×900，真实点击）：

```text
[x] 加载 → 桌面三栏；Sidebar「RSS 订阅」行尾 +（添加来源）可见
[x] 点击 + → 添加来源对话框（打开）
[x] 确认 tabs：RSS / Atom（默认选中）、网站、RSSHub
[x] RSSHub tab → 真实路由目录（14 条，经 BFF）
[x] Escape 关闭 / 重开复位 RSS/Atom
[x] 设置 → 订阅与来源：OPML 导出/导入可用、FreshRSS「连接正常，当前 4 个订阅源」
[x] 设置 → 账户与服务：无 planned·0013（FreshRSS 维护操作 · RSSHub 运营中心 · 0018）
[x] 设置 → 备份与恢复：OPML「已实现 · 0013」
[x] 设置 → RSSHub：当前 0014 / 未来 0018 描述清晰
```

MOBILE（390×844，真实点击）：

```text
[x] 收藏 tab → 文章 → 全屏 Reader（列表让位；头栏「阅读」+ 返回）
[x] Reader 动作可见（打开原文等）→ 返回 → 回到收藏列表（section/view 不变）
[x] 首页另一列表 → 文章 → 全屏 Reader → back 一致
[x] 订阅 → 添加来源 → AddSourceDialog 全屏打开（RSS/Atom · 网站 · RSSHub）
[x] 无横向溢出（scrollWidth=390）· 无 console error/warning
```

Screenshots（temporary，未提交入库）。

### Gate 5 — 路线修订（0014a 插入 + 0015–0019 定稿）

Status: Completed (2026-09-02)

已批准产品决策（用户 2026-09-02）：

```text
1. Lumi SQLite（lumi.sqlite）批准为 Lumi-owned 应用状态真源（0015 起）；
2. FreshRSS 保持 RSS-domain 唯一真源；禁止 RSS 数据影子副本；
3. Reader 数字控件使用连续有界值（0017），非仅离散预设；
4. RSSHub Control Center 批准为 0018 运营功能（typed allow-list schema）；
5. WebDAV 全量备份/恢复批准为 0018；
6. 0014a 以后缀 milestone 插入，不重排已完成的 0014。
```

文档修订：

```text
docs/ROADMAP.md        — 0014a 插入(Source Control) + 0015 新名 + 0018
                         新名(Production, Operations & Backup) + 路线变更笔记
docs/README.md         — Active/Last/Next + 账本行（0014a、0015 新标题）
docs/product/PRD.md    — v6.3：§12 开发路线对齐实际编号并定稿 0014a/0015–0019；
                         §7 数据权威表（lumi.sqlite 行 + RSSHub 配置真源 +
                         扩展硬规则）；MVP 范围 0001–0019；完成标准 0019
tools/progress-dashboard/project-data.js — phases/milestones 全量对齐
                         + currentMilestoneId 0014a→0015；JS 语法校验通过
docs/architecture/README.md §8.2 — 数据所有权边界（FreshRSS / lumi.sqlite /
                         RSSHub 配置）最小增补
```

未改写任何已完成 milestone 历史；既有编号未重排。

## Acceptance matrix（Final Gate）

```text
DESKTOP
[✓] 添加来源 visibly discoverable
[✓] opens correct existing AddSourceDialog
[✓] RSS / Website / RSSHub modes work
[✓] subscription management actions still present（订阅页 添加来源/导入/导出 OPML）
[✓] FreshRSS settings truthful（订阅与来源 = 实时状态；账户与服务 ≠ planned 0013）
[✓] RSSHub current/future capability labels truthful
MOBILE
[✓] 订阅 → 添加来源 works
[✓] 收藏 → article → full-screen Reader
[✓] Reader → back → 收藏
[✓] another list → article → Reader works consistently
[✓] no horizontal overflow（scrollWidth 390）
[✓] no obvious touch-target regression（既有 44px 控件体系未动）
DOCS
[✓] 0014a exists（本文档）
[✓] README reflects 0014a
[✓] ROADMAP reflects revised 0015–0019
[✓] PROJECT_STATE（tools/progress-dashboard/project-data.js + docs/README）updated
[✓] PRD durable decisions updated（v6.3）
[✓] no stale contradictory milestone title/reference introduced
ARCHITECTURE
[✓] no browser → FreshRSS direct call（0 处新增；全部经 BFF /api/v1）
[✓] no browser → RSSHub direct call（0 处新增；RSSHUB_BASE_URL 服务端）
[✓] no duplicate subscription state（AddSourceDialog 复用；useOpmlExportFlow 共享）
[✓] no Lumi SQLite RSS shadow-copy introduced（0014a 零 SQLite 代码）
[✓] no Docker socket exposure（零变更）
[✓] no secrets committed（BFF 零变更；临时截图未入库）
```

## Verification（Final Gate，全部通过）

```text
Web:    vitest run — 476 passed / 36 files（466 存量 + 10 新增）
BFF:    uv run pytest — 367 passed（存量，0014a 零 BFF 变更）
lint:   oxlint — 3 warnings（存量：Popover/Sidebar/FilterRulesPage）0 errors
build:  tsc -b 通过 + vite build 通过（chunk-size 提示为存量）
Playwright desktop (1440×900) + mobile (390×844) — 全流程通过（Gate 4）
```

## Git

```text
1b220d3 fix: unify mobile article reader navigation and desktop add-source entry
5c66450 docs: revise post-0014 MVP roadmap and mark 0014a acceptance
<Final>  feat: complete milestone 0014a UI acceptance（最终 commit，见 Final Gate）
```

未 push、未 merge、未创建 PR；0015 未开始（Planned 状态未变）。
