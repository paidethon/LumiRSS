# Spec — LumiRSS Minimal Project Progress Board

> 分支：`chore/project-progress-board`（已确认，基于 main `0a6a478`，工作区干净）
> Spec 交付方式：以本计划呈现，**不落盘为仓库文件**（任务 §10 的文件清单未包含 spec 文件；如希望归档到 `docs/specs/`，请在批准时说明）

## 0. 路线与文档一致性核对（任务 §4 要求先报告）

任务建议的 7 Phase / 13 Milestone（0000–0012）与 PRD v5.0 §11 Phase 0–6 逐条核对：**无冲突**。两处非冲突说明：

- **0007 Mobile + PWA**：PRD §4 将基础 PWA（manifest/图标/standalone）列为 MVP 功能，PRD §11 Phase 6 在生产链路中再次验收。看板把基础 PWA 放 Phase 3（0007），与 PRD §4 一致，不与 Phase 6 冲突。
- **0002–0004 拆分**：PRD Phase 2 要求"至少 Feed、文章列表、文章详情"，拆成 3 个 milestone 是细化，不是冲突。

## 1. Requirements

**功能需求**

- R1 单页看板 `tools/progress-dashboard/index.html`：标题 + Current Phase + Current Milestone + `2 / 13 milestones completed` + 7 阶段横向流程条（Foundation → RSS → Backend → Reading → RSSHub → AI → Production，状态至少 Completed / Current / Planned / Blocked；不用虚假百分比）
- R2 路线区域：全部 7 Phase / 13 Milestone（0000–0012），列含 Phase / Milestone ID / Name / Status / Short Goal
- R3 点击 Phase 或 Milestone → 同页详情面板（single page + JS state + detail panel，不建独立页面）。Phase 详情：名称/目的/包含的 Milestone/Completed-Planned/存在原因/当前进度；Milestone 详情：Goal / Status / What was implemented / Acceptance result / Problems encountered / What I learned / Devlog link。Desktop 右侧详情栏，Mobile 纵向详情
- R4 架构区域：README 冻结架构图原样呈现 + 显著 callout 区分「RSSHub 架构位置 = FreshRSS 上游（图中顶部，第一天就存在）」与「RSSHub 开发里程碑 = Phase 4 (0008)」
- R5 开发日志可达：链接 `../devlog/0000-project-reboot.md` 与 `../devlog/0001-freshrss-development-environment.md`（相对路径，file:// 直接打开即可访问）
- R6 当前状态忠实于仓库事实：0000 Completed / 0001 Completed / 0002 Next；未完成能力一律不显示为 Completed
- R7 全部 UI 状态由 `project-data.js` 的 `window.LUMIRSS_PROJECT` 驱动；以后更新优先只改数据，不改 HTML
- R8 单一真源：`docs/README.md` 为准，看板只是展示摘要，页面页脚注明

**非功能需求**

- N1 仅 HTML / CSS / Vanilla JS。0 依赖、0 构建。禁止 React/Vue/Svelte/Vite/npm/pnpm/Tailwind/Bootstrap/图表库/数据库/后端/GitHub API/第三方 CDN
- N2 风格 clean / minimal / reading-oriented：浅中性底色、清晰排版、细边框、合理留白；无 glassmorphism、重渐变、动画、图表、拖拽、日历、甘特图
- N3 响应式 390px / 768px / Desktop：无横向滚动、Phase 流程可读、表格不溢出、详情区手机端纵向
- N4 Secret 安全：API Password / Auth Token / Authorization Header / Cookie / 真实 Secret / .env 内容一律不得出现，必要处写 `[REDACTED]`
- N5 维护负担最小：以后 milestone 更新只触碰 `PROJECT_STATE.md` + `project-data.js` + 新增一个 devlog 文件

## 2. Design

### 2.1 文件清单（除此之外不动任何文件）

新建（4 个）：

- `tools/progress-dashboard/index.html` — 单页，内联 `<style>` + 内联渲染 `<script>`
- `tools/progress-dashboard/project-data.js` — 数据对象
- `docs/devlog/0000-project-reboot.md`
- `docs/devlog/0001-freshrss-development-environment.md`

修改（仅小幅）：

- `docs/README.md` — ① "Current phase" 一行改为 `Phase 2 — BFF (next; Phase 1 milestone 0001 completed)`，与看板"Current Phase: Phase 2"保持一致；② Current status 末尾加一行指向看板（网页展示说明）
- `README.md` — Documentation 表加一行：`tools/progress-dashboard/index.html | Project progress board (static web view of project state)`

### 2.2 页面结构（自上而下）

1. **Header**：`LumiRSS Project Board` + 三个信息块（Current Phase: Phase 2 — Backend Core / Current Milestone: 0002 BFF + FreshRSSAdapter — Next / `2 of 13 milestones completed`）+ 一行 SoT 说明
2. **Phase 流程条**：7 个节点（Foundation / RSS / Backend / Reading / RSSHub / AI / Production），每节点带状态标签与 milestone 计数（如 `1/1`、`0/3`），可点击 → Phase 详情；flex-wrap 自动换行，手机端不产生横向滚动
3. **架构区域**：`<pre>` 冻结架构图（README 原文逐行复制，含 `Non-RSS → RSSHub → FreshRSS` 顶部链路）+ RSSHub callout 框
4. **路线表**：Desktop 为表格（Phase / ID / Milestone / Status / Short Goal），Phase 表头行与 milestone 行均可点击；窄屏下行转为卡片式堆叠
5. **详情面板**：Desktop 右侧 sticky 栏（双栏 grid），Mobile 移到路线区下方全宽；默认显示当前 milestone（0002）
6. **页脚**：更新日期 + 数据源说明（PROJECT_STATE 为准）+ 一行维护规则（Milestone 完成时才更新：PROJECT_STATE → project-data.js → 新 devlog）

状态徽章（低饱和配色）：Completed 绿 / Next 蓝 / In Progress 琥珀 / Planned 灰 / Blocked 红。UI 结构标签用英文（与任务 §5 示例一致），devlog 正文用中文（沿用 spec 0001 先例：英文小节标题 + 中文内容）。

### 2.3 project-data.js 数据形状

```javascript
window.LUMIRSS_PROJECT = {
  updatedAt: "2026-08-26",
  sourceOfTruth: "docs/README.md",
  currentPhaseId: "phase-2",
  currentMilestoneId: "0002",
  phases: [
    { id: "phase-0", num: 0, name: "Foundation", label: "Phase 0 — Foundation",
      purpose: "...", why: "...", milestoneIds: ["0000"] },
    // phase-1 … phase-6 同构
  ],
  milestones: [
    { id: "0000", phaseId: "phase-0", name: "Project Reboot",
      status: "completed", shortGoal: "...",
      goal: "...", implemented: [...], acceptance: "...",
      problems: [...], learned: [...],
      devlog: "../devlog/0000-project-reboot.md" },
    // 0002: status "next"; 0003–0012: status "planned", devlog: null
  ]
};
```

状态枚举：`completed | next | in-progress | planned | blocked`。Phase 状态由成员 milestone 推导（全 completed → Completed；含 next/in-progress → Current；否则 Planned）。

### 2.4 Milestone 数据（13 条）

| ID | Name | Status | Short Goal |
|---|---|---|---|
| 0000 | Project Reboot | Completed | Rebuild repo as minimal v5.0 baseline |
| 0001 | FreshRSS Development Environment | Completed | FreshRSS 1.29.1 in Docker + API smoke test |
| 0002 | BFF + FreshRSSAdapter | **Next** | FreshRSS → FreshRSSAdapter → FastAPI /api |
| 0003 | Entry Read Path | Planned | Article list + article detail API |
| 0004 | State / Filter / Pagination | Planned | Read/star state, filters, pagination |
| 0005 | Web Shell | Planned | React app shell + layout |
| 0006 | Reader | Planned | List / read / mark / star interactions |
| 0007 | Mobile + PWA | Planned | Mobile reading flow + basic PWA |
| 0008 | RSSHub Integration | Planned | Non-RSS → RSSHub → FreshRSS real link |
| 0009 | AI Summary | Planned | On-demand summary + SQLite cache |
| 0010 | Translation | Planned | On-demand title/body translation |
| 0011 | Production Deployment | Planned | Caddy + HTTPS + Compose production |
| 0012 | Alibaba ECS + Backup / Restore | Planned | ECS deployment + backup/restore |

详情字段依据：0000/0001 的 implemented / acceptance / problems / learned 只写 Git 提交（`29b03ec`、`0a6a478`）、spec 0001、PROJECT_STATE 与 0001 会话执行记录可证明的事实；0002 详情只引用 PRD/PROJECT_STATE 的目标并注明 "Spec not written yet"；0003–0012 仅有 goal（来自 PRD §11），devlog 为 null（面板显示 Not started yet）。

Phase purpose 示例（均取自 PRD §11）：Phase 2 — Backend Core 的目的是 `FreshRSS → FreshRSSAdapter → FastAPI → /api`，存在原因是「BFF 是 LumiRSS 唯一后端，其余部分不依赖 FreshRSS API 形状」。

### 2.5 Devlog 大纲（两份均用任务 §12 模板）

**0000-project-reboot.md** — 只写 Git/文档可证事实：Status（Completed，commit `29b03ec`，PR #4）；What was implemented（删 10 个旧基线文件、重写 README/AGENTS/PR 模板/CI、新建 ARCHITECTURE+PROJECT_STATE、采用 PRD v5.0，17 files +864/−2240）；Commands（只读检查、分支创建、删除、验证命令）；Problems（旧 PRD v3.3 脚手架与 v5.0 方向冲突、工作区有用户未提交的 PRD 修改需保留）；对话无法逐字复原处一律写 `Not recorded`（核心指令以"摘要"形式标注）

**0001-freshrss-development-environment.md** — 至少覆盖：FreshRSS Docker 环境（1.29.1，127.0.0.1:8080，named volume）、浏览器初始化（SQLite、开发用户、启用 API、订阅阮一峰的网络日志、配置专用 API Password——值写 `[REDACTED]`）、ClientLogin 成功、subscription/list 成功（返回 2 个订阅）、Docker Hub 超时、镜像失败（daocloud 403 / 1ms.run ~20KB/s）、systemd drop-in 代理方案（内网 IP 部分隐去写 `172.25.x.x`，端口 7890 保留）、blob EOF 与重试。Key dialogue 3–8 段（真实关键指令/决策，Secret 全部 `[REDACTED]`）；Commands 只列真实执行过的

### 2.6 技术要点

- `<script src="project-data.js">` 同目录引用，file:// 与任意 HTTP 服务下均可加载；无 fetch/XHR/路由/存储
- 渲染 JS 约 150 行：onload 读数据 → 渲染流程条/路线表/默认详情（当前 milestone）；点击行或节点 → 重渲染详情面板并高亮选中行
- 流程条节点用 `<button>`（键盘可达）；表格行加 tabindex + role="button"

## 3. Tasks

1. 创建 `docs/devlog/0000-project-reboot.md`
2. 创建 `docs/devlog/0001-freshrss-development-environment.md`
3. 创建 `tools/progress-dashboard/project-data.js`（7 phases + 13 milestones + 详情数据）
4. 创建 `tools/progress-dashboard/index.html`（结构 + 内联 CSS + 内联 Vanilla JS）
5. 小幅修改 `docs/README.md`（current phase 澄清 + 看板指针行）
6. 小幅修改 `README.md`（Documentation 表一行）
7. 执行 Verification（见下）
8. Git 终检（任务 §23）+ 完成报告（任务 §24）；停在工作区，不 commit / push

## 4. Acceptance Criteria

| AC | 标准 | 对应设计 |
|---|---|---|
| AC1 | 仅 HTML/CSS/Vanilla JS，无新依赖 | N1；前端仅 2 个文件，无 package.json |
| AC2 | 显示 7 个 Phase | R1/R2 |
| AC3 | 显示全部 13 个 Milestone 及状态 | R2 / 2.4 |
| AC4 | 0000 Completed / 0001 Completed / 0002 Next | R6 / 2.4 |
| AC5 | 点击 Phase/Milestone 显示详情 | R3 |
| AC6 | 首页冻结架构，RSSHub 无遗漏 | R4 |
| AC7 | 可访问 0000/0001 开发日志 | R5（相对路径 + file:// 直接打开） |
| AC8 | 0001 日志含实际工作/问题/命令/对话摘要 | 2.5 |
| AC9 | 无 Secret 或已 REDACTED | N4 + V4 扫描 |
| AC10 | 390px / Desktop 正常阅读 | N3 + V3 浏览器实测 |
| AC11 | README/PROJECT_STATE 仅必要小幅说明 | 2.1 |
| AC12 | 未实现任何 LumiRSS 产品功能 | 纯静态文档页 |

## 5. Verification

- **V1 数据一致性**：用系统已有 node 载入 project-data.js，断言 7 phases / 13 milestones / 状态分布（2 completed、1 next、10 planned）/ 计数 2/13 / 已完成 milestone 的 devlog 链接文件真实存在
- **V2 服务验证**：`python3 -m http.server 8765`（仓库根）→ curl 确认 `/tools/progress-dashboard/index.html`、`/tools/progress-dashboard/project-data.js`、`/docs/devlog/0000-*.md`、`/docs/devlog/0001-*.md` 均 200（证明链接目标有效）；另按任务 §19 用 `--directory docs/progress` 验证 index.html 本身可服务，并记录该模式下 `../devlog` 相对链接超出服务根的限制（主验证模式为 file:// 直接打开，链接可达）
- **V3 浏览器实测**（Browser 子代理，本机工具不引入项目依赖）：390px / 768px / Desktop 三档截图；核对无横向滚动、流程条可读、表格不溢出、手机端详情纵向；点击 Phase 1 与 milestone 0001 行验证详情切换正确
- **V4 Secret 扫描**：对全部新增/修改文件 `grep -riE "Passwd=|auth=|Authorization:|token|password|cookie|secret"`，仅允许 `[REDACTED]` 占位或零命中
- **V5 CI 本地模拟**：repository-checks.yml 三步（必备文档 / 敏感文件 / 冲突标记）本地跑通
- **V6 Git 终检**：`git branch --show-current`（仍为 chore/project-progress-board）、`git status --short --branch`、`git diff --stat`、`git diff --check`、`git diff`；确认无 package.json / node_modules / 新依赖 / 产品代码改动 / 0002 早期实现
- **V7 双真源一致性**：PROJECT_STATE.md 与 project-data.js 的 0000/0001/0002 状态逐条比对一致

## 6. Out of scope（不做）

不实现 0002 或任何 LumiRSS 产品功能；不改冻结架构；不加任何依赖；不 commit / push / merge / rebase；不为看板扩充项目文档体系；完成报告后停下等待 review。