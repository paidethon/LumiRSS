# Spec 0009 — UI Reboot & Reference Lab

> 日期：2026-08-28
> 对应 PRD 阶段：Phase 5 — UI Reboot & Product Shell（v6.0 路线）
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**
> 批准前唯一允许写入的文件是本 Spec 与 v6 文档基线（Gate 0 产物，已批准）。
>
> 取代旧计划的 `0009 — AI Summary`（AI Summary 重新编号为 0012）。

## Goal

用一套统一的 Lumi 设计体系替换当前"功能正确但视觉临时"的 Web 外壳：

```text
0001–0008 已完成的全部行为（读取/筛选/分页/状态/移动端/PWA）
    ↓ 全部保留，零回归
semantic tokens + Lumi Mist 主题（Light / Dark / System）
    ↓
共享 UI primitives（Button / IconButton / Menu / Popover / Dialog / ...）
    ↓
响应式 App Shell + Sidebar + Timeline + Reader 视觉重建
    ↓
Folo 级交互精致度 + Lumi 自己的品牌气质（Lumi Mist / 雾光）
```

最终必须证明的结论：

> 0009 结束时，**BFF 的一行运行时代码都没有改**（API contract 零变化），
> 0001–0008 的全部行为测试仍然通过，而用户界面达到认可的视觉与交互水准。

以及两条过程纪律：

> **Folo interaction parity, not Folo product parity.**
> （学习布局/密度/状态/微交互，不复制社交/奖励/推荐/社区/商业系统）

> 整个里程碑分成 Gate 1–4 依次执行；每个 Gate 结束必须停下展示
> diff / 截图 / 测试结果，等待用户批准后才进入下一个 Gate。

0009 与 0001–0008 的本质区别：

```text
0001–0008  构建功能（后端链路 + 阅读闭环 + 移动端）
0009       重建表现层（设计体系 + 视觉），功能与数据契约冻结不动
```

一个合格的 0009 最终 Diff 形态：

```text
apps/web/src/styles/tokens.css        ← 新增 semantic tokens
apps/web/src/styles/themes.css        ← Lumi Mist Light / Dark
apps/web/src/components/ui/           ← 新增 primitives
apps/web/src/components/*             ← Sidebar / EntryList / Reader 视觉重建
apps/web/src/（既有组件按 token 迁移）
apps/web/src/__tests__/               ← 新增测试 + 既有测试适配
services/bff/                         ← 整个目录 0 文件变化（测试仅在原地重跑证明无回归）
docs/                                  ← PROJECT_STATE / Board / Devlog 更新
```

## 前置条件核对（Gate 0 已真实核验，2026-08-28）

### 分支基线（已验证）

```text
基线分支：main @ c4b84e9e4d09c080f44b99a17e35a241f27465fa（Merge PR #14）
工作分支：feat/0009-ui-reboot-reference-lab（从 main 创建，用户批准）
工作区：  仅含已批准的 v6 文档基线改动（Gate 0 产物），无其他杂项改动；
          开工前需 git status 复核并如实记录
许可证：  AGPL-3.0-only（LICENSE 已落地，用户 2026-08-28 批准）
```

### 0008 前置已满足

0001–0008 全部完成并合入 main；阅读链路（原生 RSS + RSSHub）端到端可用。

### 当前 Web 实现事实（逐文件读自仓库，非旧记忆）

- React 19 + TypeScript + Vite + Tailwind v4 + TanStack Query + Zustand + DOMPurify；
- 桌面三栏 `240px 400px 1fr`，各自滚动，`h-dvh` 整页不滚；
- <1024px 同一组件树切换 Mobile Header + Drawer + 列表↔阅读（纯 CSS media query）；
- `index.css` 仅 10 个 CSS 变量（6 个颜色：--bg/--surface/--border/--accent/--text/--text-muted + 4 个 safe-area）；
- 硬编码色散布在组件中（Gate 0 grep 实测全量清单）：`bg-blue-50`/`bg-blue-50/60`（Sidebar/EntryRow/ReaderHeader 选中态）、`hover:bg-gray-50`、`hover:bg-gray-100`、`hover:bg-blue-50`（ReaderHeader）、`text-amber-500`（星标）、`text-red-600`（错误提示）、`bg-gray-100`（骨架屏）、`border-gray-300`（retry 按钮）；
- 无图标库（当前用文本符号 ★/☰/✕）、无主题切换、无共享 primitives；
- Timeline 行仅 title/feedTitle/author/publishedAt/read/starred——**当前 API 无摘要/favicon/缩略图字段**。

### 参考基线（已克隆、已核验、SHA 钉死）

| 项目 | 分支 | SHA | 许可证 | 用途 |
|---|---|---|---|---|
| Folo | dev | `78f6bd1b745ba5d85027f6ca85ce60b06ca46569` | AGPL-3.0 + icons/mgc 例外 | 首要交互参考 |
| OrigRead (Android) | main | `18d3281de241fabc22c94d4cacb965ec1eaa1430` | GPL-3.0 | 移动端模式参考 |
| OrigRead-Desktop | main | `8b59bcb4ec63c4514e06e3863b1bc527eed861dd` | AGPL-3.0-only | Settings/阅读工具参考 |

位置：`~/projects/LumiRSS-reference/`（仓库外、只读、非 submodule）。
实机测量数据与源码路径见 `docs/reference/UPSTREAMS.md` §3/§7。

### Folo 实测关键数字（本 Spec 的视觉锚点）

```text
Sidebar 行：高 32px、pad 2px 10px、radius 6px、字号 14px/500、hover 200ms
Timeline 行：~108px、favicon 24×24、来源行 10px/700/50% 透明、
             标题 14px/500 两行、摘要 13px 次要色、缩略图 80×80
Reader 标题：27.2px/700、正文 prose 容器、工具栏按钮 32×32/r6
主题机制：html[data-theme] + --fo-* 语义变量（oklab/hsl）
hover/selected：低透明度中性色（oklab 37.1% 0 0/.3 与 43.9% 0 0/.4），非彩色填充
滚动条：thumb 6px；三栏均可拖分隔条（Sidebar 256–300、Timeline 300–600）
```

### 测试基线（2026-08-28 真实重跑）

```text
BFF：uv run pytest        → 121 passed（0.80s，1 个 starlette deprecation warning）
Web：pnpm test            → 121 passed（9 个测试文件）
     pnpm lint            → 0 warnings / 0 errors（oxlint, 28 files）
     pnpm build           → 成功（79 modules, js 274KB / gzip 86.9KB）
```

## Context — 概念解释（写给初学者）

### 为什么 0009 在 AI 之前

0005–0007 的 UI 是"能用的临时外壳"。如果在其上继续叠加 AI 面板、订阅
管理、设置中心，每个新页面都会复制一遍临时样式，未来重做成本翻倍。
先重建视觉体系，后续所有功能都直接受益。

### semantic token 是什么

不是每个组件自己写 `bg-blue-50`，而是统一定义变量：

```css
--lumi-surface-selected: oklch(...);
--lumi-accent: #6d78e8;
```

组件只引用变量。换主题 = 换变量值，组件零改动。Folo 的 `--fo-*`
体系就是这么做的（实测数据见上）。

### Light / Dark / System

System 模式跟随 `prefers-color-scheme`；用户显式选择优先于系统。
主题落在 `<html data-theme="...">`，与 Folo 同机制。

### App Theme 与 Reader Theme 分离

阅读长文时用户可能想要暖色纸感背景，但不想整个 App 变暖。
Reader 背景是独立设置（跟随 App / 冷白 / 暖白 / 纸黄等）。

### "interaction parity" 的边界

学习：布局、密度、层级、状态、微交互、动效时长。
拒绝：社区、奖励、推荐流、公开 Profile、商业系统——它们是 Folo 的
产品，不是 Lumi 的。

### UI Reboot 为什么零 BFF 改动

Timeline 想要摘要/缩略图/favicon，但当前 API 没有。正确做法：
用现有字段做优雅降级布局，把字段缺口记录为未来 API 契约需求
（0010+），**绝不**为了 UI 好看偷偷改 BFF，更不在浏览器里抓取。

## Scope（只做这些）

1. **Gate 1 — Design Foundation**
   - `styles/tokens.css`：surface/text/border/accent/分类色/圆角/阴影/动效/层级 全套语义 token；
   - `styles/themes.css`：Lumi Mist Light + Dark；
   - System / Light / Dark 切换 + 本地偏好持久化（localStorage，文档化临时方案，0014 迁移服务端）；
   - reduced-motion 支持；
   - 图标决策：现状是文本符号（★☰✕），评估 `lucide-react`（ISC）或维持/扩充文本+SVG 方案——**引入新依赖前单独请示用户**；
   - Primitives 第一批：Button、IconButton、Tooltip、Menu、Popover、Select、Dialog/Sheet、Switch、Skeleton、EmptyState（可访问、无业务逻辑）；
   - dev-only 视觉 playground 路由（验证 primitives 各状态，不进生产导航）。
2. **Gate 2 — App Shell + Sidebar + Timeline**
   - App Shell：CSS Grid 重构（Sidebar 220–260 / Timeline 360–440 / Reader minmax(0,1fr)）、pane 分隔线层级、overlay 挂载点；
   - Sidebar：品牌区、All/Unread/Starred、真实 feeds（分类色仅小图标/圆点/低透明 tint）、hover/selected/focus 态、32px 行高密度；
   - Timeline：连续列表（非卡片堆叠）、来源·时间行/标题/摘要层级、read/unread/starred 状态、无摘要时的降级布局、loading/empty/error 态。
3. **Gate 3 — Reader + Responsive + Theme**
   - Reader：紧凑工具栏、27px 级标题、正文最大宽度（~720–780px）与行高节奏、Reader Theme 钩子（独立背景变量）；
   - 移动端精化：列表行/阅读页布局、触摸目标 ≥44px、safe-area 保留；
   - 三态主题全链路验证（App + Reader 独立背景）。
4. **Gate 4 — Polish + Regression**
   - hover/active/focus 全量、menu/popover 动效（120–160ms）、scrollbar/divider 统一；
   - 键盘可达性与 focus-visible；
   - 视口矩阵截图（1920/1440/1024/820/390）before/after 对照；
   - 全量测试/lint/build + 真实浏览器 smoke；
   - Settings 壳与 overlay 系统统一（**仅视觉结构**，已支持的 Appearance 控件可真实工作，Sources/AI 等占位控件必须明确标注 planned，不假装可保存）。

## Non-goals（明确不做，做了就是 scope creep）

- AI runtime / AI 面板真实功能（0012–0013）；
- Feed CRUD / 订阅 API（0010）；
- RSSHub route builder / 来源发现（0011）；
- Source Resolver / 网页抓取 / JSON API 来源 / 邮件 / Obsidian / Agent（Phase 2）；
- SQLite schema / 任何后端持久化；
- Caddy / production 部署 / Docker 架构重写；
- Service Worker / 离线缓存；
- Folo 社交/推荐/奖励/公开 Profile；
- 多用户 / 注册 / OAuth；
- 原生 iOS / Android App；
- 直接复制 Folo `icons/mgc`（**任何情况下禁止**）；
- 为"以后可能需要"建立空抽象/空目录；
- 一次性把 Folo 所有功能搬进来。

## 硬边界（冻结，0009 不得触碰）

1. **BFF 零变化**——`git diff main -- services/bff` 为空：API contract、entryRef/cursor 不透明性、错误映射全部冻结；
2. 浏览器只访问 `/api/v1/*`（相对路径），永不直连 FreshRSS/RSSHub/AI；
3. 打开文章不自动标记已读；read/starred 写入保持 set 语义；
4. DOMPurify 清洗边界（`sanitize-article-html` + 唯一 `dangerouslySetInnerHTML`）不得削弱——不为更好看的嵌入放宽 iframe/script/style；
5. `safeExternalHttpUrl` 原文链接安全规则不变；
6. 移动端 list↔reader 返回流（selectedEntryRef 驱动、Query cache 复用）不回退；
7. PWA 不宣传离线能力；
8. TanStack Query 拥有 server state、Zustand 仅轻量 UI state 的边界不重写；
9. 上游代码借鉴必须走 `SOURCE_MAP.md` 登记（inspired/rewritten/adapted/copied + SHA + 路径）；
10. 认证/私人截图、浏览器 profile、cookies 永不入 Git。

## 设计规格（冻结基线，实现时按实测微调并记录）

详细规格见 `docs/ui/UI_REBOOT.md`（已批准）。Spec 级冻结要点：

### Token 体系（--lumi-* 前缀）

```text
surface 族：canvas / sidebar / surface / surface-elevated / reader
            surface-hover / surface-selected / surface-pressed
text 族：   primary / secondary / tertiary / disabled
边框族：    border / separator / focus-ring
accent 族： accent / accent-hover / accent-pressed / accent-soft / accent-contrast
分类色：    blue / green / orange / purple / cyan / rose / red（低饱和柔彩）
阴影族：    shadow-popover / shadow-dialog / shadow-floating（仅浮层用）
圆角：      4 / 6 / 8 / 10 / 12 / 14 / 16 / 999px——nav item 与按钮 ~8px，
            popover/设置组 10–12px，AI 面板 16px；禁止全组件 rounded-xl/2xl
动效：      hover 100–120ms、menu 120–160ms、drawer/panel 180–220ms；
            禁止 hover scale / 弹跳 / 发光 / 卡片上浮；必须响应
            prefers-reduced-motion
```

### Lumi Mist 默认色板（起始候选，Gate 1 对照实测校准）

```text
Light：canvas #f6f4f4 / sidebar #f1eeee / surface #fbfafa / accent #6d78e8
Dark： canvas #18181a / sidebar #1d1d20 / surface #222226 / accent #8993f5
```

### 组件状态规则

- selected：低透明度中性 tint（参考 Folo oklab .3/.4 实测），非浓色大卡片；
- unread：字重 + 圆点，不只靠颜色；
- hover 只做 surface 变化（200ms 级），无位移无阴影。

## Acceptance Criteria

| # | 验收标准 |
|---|---|
| AC1 | 分支隔离：全部工作在 feat/0009-ui-reboot-reference-lab，main 不受影响；每个 Gate 结束停下等用户批准 |
| AC2 | BFF 零变化：`git diff main --stat -- services/bff` 为空——整个 services/bff 目录（含代码与文档）0009 期间零改动，测试仅在原地重跑以证明无回归 |
| AC3 | semantic tokens：迁移后的组件不再出现硬编码颜色类，全量清单 grep 清零：bg-blue-50（含 /60 变体）/ hover:bg-gray-50 / hover:bg-gray-100 / hover:bg-blue-50 / text-amber-500 / text-red-600 / bg-gray-100 / border-gray-300 |
| AC4 | Lumi Mist Light + Dark 双主题完整可用；`html[data-theme]` 机制；Dark 为多层深灰非纯黑 |
| AC5 | System / Light / Dark 三态切换可用，刷新后偏好保持（localStorage 临时方案已在文档记录迁移路径） |
| AC6 | reduced-motion 偏好下关闭非必要动效 |
| AC7 | Primitives（Button/IconButton/Tooltip/Menu/Popover/Select/Dialog/Sheet/Switch/Skeleton/EmptyState）可访问：键盘可达、focus-visible、Dialog focus trap + Escape、aria label |
| AC8 | App Shell：三栏 CSS Grid、Reader `min-width: 0`、各栏独立滚动、分隔线层级清晰、无外层卡片包裹 |
| AC9 | Sidebar：≥ Folo 密度（行高 ~32px）、hover/selected/focus 三态可区分、分类色仅点缀用途、桌面与移动 Drawer 复用同一组件与数据 |
| AC10 | Timeline：连续列表非卡片堆叠；来源/时间/标题层级清晰；read/unread/starred 状态不只靠颜色；无摘要/缩略图时降级布局干净（无空洞分隔符） |
| AC11 | Timeline 数据行为不变：view/feed 过滤、cursor 分页、Load More、选中项跨页保持清晰 |
| AC12 | Reader：标题/正文层级与最大宽度（~720–780px）、工具栏紧凑可访问、显式 read/star 按钮保留且行为不变 |
| AC13 | DOMPurify 清洗边界与 `safeExternalHttpUrl` 测试原样通过（未削弱） |
| AC14 | Reader Theme 与 App Theme 分离：Reader 背景可独立于 App 主题设置 |
| AC15 | 移动端流程完整保留：Drawer 开/关/Escape/导航、list↔reader 返回不 reload、触摸目标 ≥44px、safe-area 生效 |
| AC16 | 视口矩阵（1920×1080 / 1440×900 / 1024×768 / 820×1180 / 390×844）无横向溢出、无布局破坏，before/after 截图留档 |
| AC17 | 视觉 playground 仅 dev 可达，不进生产导航 |
| AC18 | Settings 壳仅为视觉结构：可工作的只有 Appearance 类控件；Sources/AI 等占位明确标注 planned，不存在假装可保存的控件 |
| AC19 | 无未来功能假实现：无 AI 控件、无订阅按钮通向不存在的 API、无 RSSHub UI |
| AC20 | 上游溯源：任何 inspired/rewritten/adapted 借鉴登记进 SOURCE_MAP.md；Folo icons/mgc 零复制（grep/文件树可验证） |
| AC21 | 新依赖：默认 0 新增；若 Gate 1 提议 lucide-react 等，先单独请示用户并说明体积/许可证/替代方案，批准后才安装 |
| AC22 | 既有测试全量通过或诚实隔离报告：BFF 121、Web 测试适配 token/结构变化后全绿、lint 0、build 成功（记录真实数字） |
| AC23 | 真实浏览器 smoke：FreshRSS 真数据下 Feed → 过滤 → 阅读 → read/star（可逆恢复）全流程 + 浏览器 console 无 error + network 无前端直连 FreshRSS/RSSHub |
| AC24 | 无 Secret/私人数据入库：认证截图零提交（本地截图放 gitignored 目录或仅记录测量值）、.env 未 tracked |
| AC25 | Scope：未实现 Non-goals 清单中任何一项；无 Phase 2 提前实现 |
| AC26 | 文档同步：PROJECT_STATE / Board / Devlog / README 与实际一致；Gate 0 产物（docs/reference 三件套）保持准确 |
| AC27 | 全部 Gate 通过并经用户批准后，0009 → Completed，0010 → Next（不启动） |

## Tasks（Build 顺序，批准后严格逐步执行，每步完成立即验证）

### Gate 1（用户批准本 Spec 后开始）

1. `styles/tokens.css` + `styles/themes.css`（Lumi Mist Light/Dark 起始色板）；
2. `data-theme` 挂载 + System/Light/Dark 切换器（临时 UI 放 playground）+ localStorage 持久化 + reduced-motion；
3. 图标决策报告（现状盘点 + lucide-react 建议 + 体积/许可对比）→ **请示用户**；
4. Primitives 逐个实现（每个含 a11y 属性 + 测试）；
5. dev playground 路由（primitives × 主题 × 状态矩阵）；
6. Gate 1 验证：playground 截图（Light/Dark × 桌面/移动宽度）+ lint/test/build → **停，等批准**。

### Gate 2

7. App Shell Grid 重构（保持 lg 断点行为）；
8. Sidebar 重建（token 化 + Folo 密度）；
9. Timeline 重建（EntryRow 层级 + 降级布局 + 状态）；
10. 既有测试适配 + 新增状态测试；
11. Gate 2 验证：1440 Light/Dark、1024 紧凑、390 Drawer 截图 + 全量测试 → **停，等批准（未批准不进 Reader）**。

### Gate 3

12. Reader 视觉重建（工具栏/排版/宽度）+ Reader Theme 钩子；
13. 移动端精化（行/阅读页/触摸/safe-area 复核）；
14. 三态主题全链路 + Reader 独立背景验证；
15. Gate 3 验证：Reader Light/Dark + 移动截图 + DOMPurify/safe-link 测试确认 → **停，等批准**。

### Gate 4

16. Settings 壳 + overlay 统一（视觉结构）；
17. 全量 polish（hover/focus/动效/scrollbar/divider/键盘）；
18. 视口矩阵截图 before/after；
19. 全量回归（BFF 121 + Web 全绿 + lint + build）+ 真实浏览器 smoke（可逆状态恢复）；
20. 文档收尾（PROJECT_STATE / Board / Devlog / README）→ **停，等最终批准**。

## Verification

```text
V1  git diff main --stat -- services/bff        → 空输出（目录级零变化）
V2  grep -rn "bg-blue-50\|hover:bg-gray-50\|hover:bg-gray-100\|hover:bg-blue-50\|
    text-amber-500\|text-red-600\|bg-gray-100\|border-gray-300" apps/web/src
    → 迁移范围内 0 命中（若某文件在后续 Gate 才迁移，在 Gate 计划中列出）
V3  html[data-theme] 三态切换 + 刷新保持（真实浏览器验证）
V4  prefers-reduced-motion 模拟下动效关闭
V5  键盘走查：Tab 全程可见 focus、Dialog/Sheet trap + Escape 还焦
V6  视口矩阵截图（Playwright，5 尺寸 × Light/Dark）无横向溢出
V7  cd services/bff && uv run pytest            → 121 passed（回归证明）
V8  cd apps/web && pnpm test && pnpm lint && pnpm build → 全绿（真实数字）
V9  真实浏览器 smoke（FreshRSS 真数据）：导航/过滤/阅读/可逆 read/star，
    console 零 error，network 无 FreshRSS/RSSHub 直连
V10 SOURCE_MAP.md 登记完整；find/grep 证明无 icons/mgc、无认证截图
V11 git ls-files --others --exclude-standard 扫描无 Secret/私人数据
```

## Documentation updates（AC 全过后单独做）

- `docs/PROJECT_STATE.md`：0009 → completed，测试/截图证据填入；
- `docs/progress/project-data.js`：0009 详情 + devlog 链接，0010 → next；
- `docs/devlog/0009-ui-reboot-reference-lab.md`：新建（含 Folo 对照结论、Gate 逐段记录、未验证项诚实清单）；
- `README.md`：Current status 更新；
- `docs/reference/SOURCE_MAP.md`：实现中实际发生的借鉴逐条登记；
- `THIRD_PARTY_NOTICES.md`：若新增依赖则补登记。

## Risks / Unknowns

- **视口工具限制**：Qoder 浏览器面板无法任意 resize；Gate 4 截图矩阵将用 Playwright MCP（0007 曾因浏览器二进制下载受限失败，届时重试或如实标注 UNVERIFIED）；
- **Timeline 字段缺口**：摘要/favicon/缩略图不在当前 API——降级布局先行，字段需求记录给 0010+（不阻塞 0009）；
- **主题持久化是临时方案**：localStorage + 0014 迁移注记（无设置 API 前不发明后端）；
- **动效手感**：时长数字是规格不是保证；Gate 2/3 审图时以您的实际感受为准微调；
- **lucide-react 依赖**：默认不装；若批准，需评估 tree-shaking 后体积（预估 <30KB gzip 常用子集）。

## 与任务指令的对应关系

本 Spec 依据 QODER_MASTER_INSTRUCTION.md §11（视觉配方）、§12（响应式）、
§15（Gate 1–4）、§16（绝对不做）、§17（视觉验收）、§18（测试）编写，
并与已批准的 `docs/ui/UI_REBOOT.md`、`docs/PRD.md` v6.0 对齐；冲突时以
用户指令与 PRD 为准。
