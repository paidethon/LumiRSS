// LumiRSS Project Board — data source
// ---------------------------------------------------------------
// This file is a web-view SUMMARY of docs/PROJECT_STATE.md.
// If the two ever disagree, PROJECT_STATE.md wins.
//
// How to update (only when a milestone starts or completes):
//   1. Update docs/PROJECT_STATE.md (the source of truth).
//   2. Update the milestone entry here:
//      - starting:  status "planned" -> "in-progress"
//      - completing: status -> "completed", fill implemented /
//        acceptance / problems / learned, set devlog link, and
//        mark the next milestone "next"; update currentPhaseId /
//        currentMilestoneId / updatedAt.
//   3. Add docs/devlog/<milestone>.md.
// Do NOT rewrite index.html for progress updates.
//
// Milestone status values:
//   "completed" | "next" | "in-progress" | "planned" | "blocked"
// ---------------------------------------------------------------

window.LUMIRSS_PROJECT = {
  updatedAt: "2026-08-26",
  sourceOfTruth: "docs/PROJECT_STATE.md",
  currentPhaseId: "phase-2",
  currentMilestoneId: "0002",

  phases: [
    {
      id: "phase-0",
      num: 0,
      name: "Foundation",
      label: "Phase 0 — Foundation",
      purpose: "建立清晰、最小的 v5.0 新仓库基线：只保留 README、PRD、ARCHITECTURE、PROJECT_STATE、AGENTS 和 Git 基础保护。",
      why: "旧仓库带有与 v5.0 方向冲突的脚手架文档；先收敛基线，才能在干净的地基上开始真实开发。",
      milestoneIds: ["0000"]
    },
    {
      id: "phase-1",
      num: 1,
      name: "RSS",
      label: "Phase 1 — RSS Foundation",
      purpose: "Docker → FreshRSS → 浏览器可访问 → API 可认证 → 读取真实订阅。LumiRSS 第一个真正运行的里程碑。",
      why: "FreshRSS 是冻结架构中唯一的 RSS 真源；先让它在开发机真实运行并验证 API，BFF 才有可靠的数据源。",
      milestoneIds: ["0001"]
    },
    {
      id: "phase-2",
      num: 2,
      name: "Backend",
      label: "Phase 2 — Backend Core",
      purpose: "FreshRSS → FreshRSSAdapter → FastAPI → /api，至少完成 Feed、文章列表和文章详情。",
      why: "BFF 是 LumiRSS 唯一的后端；Adapter 让项目其余部分不依赖 FreshRSS 的 API 形状。这是前端开工的前提。",
      milestoneIds: ["0002", "0003", "0004"]
    },
    {
      id: "phase-3",
      num: 3,
      name: "Reading",
      label: "Phase 3 — Reading Experience",
      purpose: "React → FastAPI → FreshRSS：完成列表、阅读、已读、收藏、Desktop 与 Mobile 体验。",
      why: "阅读体验是 LumiRSS 的真正价值；本阶段结束后，LumiRSS 应该已经可以真正用于阅读。",
      milestoneIds: ["0005", "0006", "0007"]
    },
    {
      id: "phase-4",
      num: 4,
      name: "RSSHub",
      label: "Phase 4 — Source Expansion",
      purpose: "网站 → RSSHub → FreshRSS → LumiRSS，只解决真实需要 RSSHub 的订阅源。",
      why: "RSSHub 在架构上始终位于 FreshRSS 上游（见架构图）；开发上放到这里落地——先保证主阅读链路干净，再扩展内容来源。",
      milestoneIds: ["0008"]
    },
    {
      id: "phase-5",
      num: 5,
      name: "AI",
      label: "Phase 5 — AI Enhancement",
      purpose: "增加按需摘要、翻译与 SQLite 缓存。",
      why: "AI 是可选增强：用户主动触发、结果归 LumiRSS 自己（存 SQLite），AI 故障不得阻塞普通阅读。",
      milestoneIds: ["0009", "0010"]
    },
    {
      id: "phase-6",
      num: 6,
      name: "Production",
      label: "Phase 6 — Production",
      purpose: "Docker Compose → Caddy → HTTPS → 阿里云 ECS → Desktop / Mobile / PWA，随后增加备份与恢复。",
      why: "最终形态是单台普通 Linux 服务器上的自托管部署：简单、可备份、可恢复。",
      milestoneIds: ["0011", "0012"]
    }
  ],

  milestones: [
    {
      id: "0000",
      phaseId: "phase-0",
      name: "Project Reboot",
      status: "completed",
      shortGoal: "Rebuild repo as minimal v5.0 baseline",
      goal: "把旧的“多文档脚手架”仓库收敛成最小、清晰、可继续开发的新基线：采用 PRD v5.0，删除旧基线文件，重写核心文档，让新 Agent 只靠 Git 仓库就能理解项目。",
      implemented: [
        "删除 10 个旧基线文件（旧 specs/audits、issue 与 dependabot 模板、.lingma 规则、.env.example、.aiignore.md）",
        "采用 PRD v5.0 — Reboot Baseline 作为最高产品依据",
        "重写 README / AGENTS / PR 模板 / CI 检查为极简版",
        "新建 docs/ARCHITECTURE.md 与 docs/PROJECT_STATE.md"
      ],
      acceptance: "全部验收通过：目录结构与目标一致、PRD 为 v5.0、旧文件名零残留、CI 三步本地模拟通过、workflow YAML 有效。提交 29b03ec（17 files，+864/−2240），经 PR #4 合入 main。",
      problems: [
        "旧 PRD v3.3 与大量脚手架文档和 v5.0 的极简方向冲突",
        "工作区存在用户手动更新的 PRD v5.0 未提交修改，必须原样保留"
      ],
      learned: [
        "聊天记录不是项目知识库，Git 仓库才是（PRD v5.0 §2 把这条固化成了原则）",
        "大规模删除前先确认备份分支存在：archive/pre-wsl-reset 保留全部旧历史，删错可找回",
        "文档体系的复杂度本身就是维护负担，最小够用优于完备"
      ],
      devlog: "../devlog/0000-project-reboot.md"
    },
    {
      id: "0001",
      phaseId: "phase-1",
      name: "FreshRSS Development Environment",
      status: "completed",
      shortGoal: "FreshRSS 1.29.1 in Docker + API smoke test",
      goal: "用 Docker Compose 启动 FreshRSS，浏览器完成初始化（开发用户、真实 RSS、专用 API Password），再用 Google Reader API 的 ClientLogin 认证并实际读取订阅列表，证明数据源链路可用。",
      implemented: [
        "docker-compose.yml：FreshRSS 1.29.1 单服务，绑定 127.0.0.1:8080，named volume 持久化",
        "浏览器初始化：SQLite 数据库（开发期便利）、开发用户、启用 API 访问、订阅真实 RSS（阮一峰的网络日志）、配置专用 API Password",
        "ClientLogin 认证成功（HTTP 200 + Auth token），subscription/list 返回 2 个订阅",
        "Docker daemon 代理（systemd drop-in）解决镜像拉取超时",
        "更新 README / PROJECT_STATE，新增 spec 0001"
      ],
      acceptance: "Spec 0001 的 6 条验收全部达成：容器运行、浏览器可登录、订阅含真实 RSS、API Password 已配置、ClientLogin 200 + token、subscription/list 返回真实订阅。提交 0a6a478。",
      problems: [
        "Docker Hub 直连超时（registry-1.docker.io 不可达）",
        "公共镜像源不可用或极慢：daocloud 403、docker.1ms.run 约 20KB/s",
        "配置代理后大 blob 多次 EOF 中断，371MB 镜像靠多次重试拉完"
      ],
      learned: [
        "Google Reader API 认证流：ClientLogin(Email + Passwd) → Auth token → Authorization: GoogleLogin auth=…",
        "Docker daemon 代理是系统级配置（systemd drop-in + restart），不是 shell 环境变量",
        "凭据只存在于浏览器会话与 Docker volume，收尾 grep 扫描仓库零命中"
      ],
      devlog: "../devlog/0001-freshrss-development-environment.md"
    },
    {
      id: "0002",
      phaseId: "phase-2",
      name: "BFF + FreshRSSAdapter",
      status: "next",
      shortGoal: "FreshRSS → FreshRSSAdapter → FastAPI /api",
      goal: "搭建 LumiRSS 自己的后端骨架：FastAPI BFF + FreshRSSAdapter，通过 /api 读出 Feed 列表，打通 FreshRSS → Adapter → BFF 的第一条数据链路（目标出自 PRD §11 Phase 2 与 PROJECT_STATE）。",
      implemented: [],
      acceptance: "Spec not written yet — 开工时按 PRD §10 先写 spec 再实现。",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0003",
      phaseId: "phase-2",
      name: "Entry Read Path",
      status: "planned",
      shortGoal: "Article list + article detail API",
      goal: "在 0002 的链路上补全 Entry 读取：文章列表与文章详情 API，与 0002 共同达成 Phase 2 的最小集。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0004",
      phaseId: "phase-2",
      name: "State / Filter / Pagination",
      status: "planned",
      shortGoal: "Read/star state, filters, pagination",
      goal: "补全 Phase 2 的后端能力：已读/收藏状态写入、未读/收藏/Feed/分类筛选与分页。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0005",
      phaseId: "phase-3",
      name: "Web Shell",
      status: "planned",
      shortGoal: "React app shell + layout",
      goal: "搭建 React 应用外壳与整体布局骨架（导航 / 文章列表 / 阅读区），接入 BFF /api。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0006",
      phaseId: "phase-3",
      name: "Reader",
      status: "planned",
      shortGoal: "List / read / mark / star interactions",
      goal: "完成阅读闭环：文章列表、阅读正文、标记已读、收藏/取消收藏，先做 Desktop 体验。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0007",
      phaseId: "phase-3",
      name: "Mobile + PWA",
      status: "planned",
      shortGoal: "Mobile reading flow + basic PWA",
      goal: "移动端“列表 → 详情 → 返回”的纵向阅读流，加上基础 PWA（manifest / 图标 / standalone 启动）。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0008",
      phaseId: "phase-4",
      name: "RSSHub Integration",
      status: "planned",
      shortGoal: "Non-RSS → RSSHub → FreshRSS real link",
      goal: "证明至少一条真实链路：非 RSS 网站 → RSSHub → FreshRSS → LumiRSS。只解决真实需要 RSSHub 的订阅源，不做 Route 搜索/编辑器。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0009",
      phaseId: "phase-5",
      name: "AI Summary",
      status: "planned",
      shortGoal: "On-demand summary + SQLite cache",
      goal: "用户主动触发的单篇摘要（OpenAI-compatible API），结果与缓存存入 SQLite；AI 关闭或失败不影响阅读。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0010",
      phaseId: "phase-5",
      name: "Translation",
      status: "planned",
      shortGoal: "On-demand title/body translation",
      goal: "用户主动触发的标题/正文翻译，尽量复用缓存；失败明确显示状态，不阻塞阅读。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0011",
      phaseId: "phase-6",
      name: "Production Deployment",
      status: "planned",
      shortGoal: "Caddy + HTTPS + Compose production",
      goal: "生产形态：Caddy（HTTPS + 静态资源 + /api 反代）+ Docker Compose 单机部署。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0012",
      phaseId: "phase-6",
      name: "Alibaba ECS + Backup / Restore",
      status: "planned",
      shortGoal: "ECS deployment + backup/restore",
      goal: "部署到阿里云 ECS，并完成数据备份与恢复流程。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    }
  ]
};
