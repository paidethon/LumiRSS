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
  updatedAt: "2026-08-28",
  sourceOfTruth: "docs/PROJECT_STATE.md",
  currentPhaseId: "phase-3",
  currentMilestoneId: "0006",

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
      status: "completed",
      shortGoal: "FreshRSS → FreshRSSAdapter → FastAPI /api",
      goal: "搭建 LumiRSS 自己的后端骨架：FastAPI BFF + FreshRSSAdapter，通过 /api 读出 Feed 列表，打通 FreshRSS → Adapter → BFF 的第一条数据链路（目标出自 PRD §11 Phase 2 与 PROJECT_STATE）。",
      implemented: [
        "services/bff 最小 FastAPI 骨架（uv 管理，src 布局，手工 pyproject + uv.lock）",
        "FreshRSSAdapter：async ClientLogin + subscription/list，Token 仅存进程内存，401 时一次性重登",
        "归一化为最小 LumiRSS Feed 模型（title + feedUrl）",
        "GET /health/live 与 GET /api/v1/feeds 两个路由",
        "懒创建配置/Adapter（lifespan 只管共享 AsyncClient，health 不依赖 FreshRSS 配置）",
        "15 个自动化测试全 Mock（health/ClientLogin解析/映射/配置秘密/route wiring/错误映射）",
        "真实 Smoke Test：curl /api/v1/feeds 返回真实订阅（FreshRSS releases + 阮一峰的网络日志）",
        "故障验证：无效凭据 → 502 authentication_error，无泄漏、不崩溃"
      ],
      acceptance: "Spec 0002 的 AC1–AC10 全部达成：分支隔离、BFF 启动、health 200、配置来自环境且 Secret 不进 Git、ClientLogin 真实成功且 Token 仅内存、subscription 真实读取、/api/v1/feeds 真实返回订阅、15 个测试通过、secret 扫描零命中、无越界实现。",
      problems: [
        "PyPI 网络不稳：uv sync 首次 5 分钟超时，拉取 hatchling 构建依赖时连接中断，重试后成功",
        "首个测试发现 bug：ClientLogin 请求本身的连接错误未映射为 UpstreamConnectionError，修复后 15/15 通过",
        "route 测试初版在 lifespan 启动前注入 fake adapter 被 lifespan 重置，改为启动后注入"
      ],
      learned: [
        "httpx.AsyncClient + trust_env=False 避免 WSL/Windows 代理劫持 localhost 请求",
        "pydantic SecretStr 防止 repr/日志泄漏密码；空字符串密码必须视为无效配置",
        "TestClient 的 with 语句会触发 lifespan，测试注入依赖要在启动后进行",
        "懒创建 Adapter 让 /health/live 与 FreshRSS 配置彻底解耦"
      ],
      devlog: "../devlog/0002-bff-freshrss-adapter.md"
    },
    {
      id: "0003",
      phaseId: "phase-2",
      name: "Entry Read Path",
      status: "completed",
      shortGoal: "Article list + article detail API",
      goal: "在 0002 的链路上补全 Entry 读取：文章列表与文章详情 API，与 0002 共同达成 Phase 2 的最小集。",
      implemented: [
        "GET /api/v1/entries：reading-list（n=20，read+unread），主动丢弃正文，只返回列表字段",
        "GET /api/v1/entries/{entryRef}：POST stream/items/contents（单个 i），正文转安全纯文本 contentText",
        "entryRef：e1. + base64url(upstream id)，URL-safe/opaque/可逆；非法 ref 在触达 FreshRSS 前拒绝（400）",
        "EntryNotFound：上游对不存在 item 返回 200+空 items → 映射 404；多 item 防御性 UpstreamError",
        "HTML→text：标准库 HTMLParser（tag 剥离/entity 还原/段落换行/script+style 内容丢弃），0 新依赖",
        "严格只读：MockTransport 断言只触达 ClientLogin/reading-list/items/contents，无任何写 endpoint",
        "43 个新增自动化测试（全部 Mock），含 0002 回归共 58 个通过",
        "真实 Smoke Test：13 条真实文章列表 + 详情 200（contentText 5804 字）+ 400/404 验证"
      ],
      acceptance: "Spec 0003 的 AC1–AC14 全部达成：分支隔离、0002 无回归、真实文章列表（n=20 上限）、列表模型不含正文、entryRef 全部性质、真实详情、contentText 纯文本、缺字段不 500、400/404/502 错误映射、58 测试通过、真实 Smoke 链路、只读性断言、无越界实现。",
      problems: [
        "Build 前修订：Detail endpoint 从未知假设改为源码已验证（POST stream/items/contents + form i=），Live Probe 确认真实容器与源码一致",
        "reading-list 语义修正：All except hidden，无 it/xt 时 STATE_ALL（已读+未读），非“未读优先”",
        "两次编辑事故（docstring 与 try 粘连、UpstreamError 类误删）由测试立即暴露并修复",
        "手写期望时间戳算错一次，以 datetime.fromtimestamp 为准修正测试"
      ],
      learned: [
        "FreshRSS items/contents 对不存在 item 返回 200+空 items 而非 404——Adapter 层要做“空即 404”映射",
        "entryRef 版本前缀（e1.）+ base64url 是“不透明引用”的最小实现：无签名/无数据库/无 UUID 就够用",
        "List 接口即使上游已带正文也必须主动丢弃——否则列表接口变成正文批量下载器",
        "标准库 html.parser 足够做 text-only normalization（不是 sanitizer）：tags 剥离+entity 还原+块级换行+script 丢弃"
      ],
      devlog: "../devlog/0003-entry-read-path.md"
    },
    {
      id: "0004",
      phaseId: "phase-2",
      name: "State / Filter / Pagination",
      status: "completed",
      shortGoal: "Read/star state, filters, cursor pagination",
      goal: "补全 Phase 2 的后端能力：已读/收藏状态写入、未读/收藏/Feed 筛选与游标分页（Category 筛选 deferred 到后续里程碑）。",
      implemented: [
        "Entry list/detail 新增 read/starred 布尔字段（来自 FreshRSS categories 状态 marker，缺失容错 false）",
        "GET /api/v1/entries?view=all|unread|starred：view 翻译为上游 it= 参数，由 FreshRSS 筛选，无 Python post-filter",
        "GET /api/v1/entries?feedUrl=<url>：feed URL percent-encode 进 feed stream path；可与 view 组合（同一上游请求）",
        "游标分页：cursor/nextCursor 不透明封装（c1. + base64url JSON，携带 continuation + view + feedUrl scope），不暴露原始 continuation；cursor 可独立请求下一页；scope 不匹配 400 且不触达 FreshRSS",
        "PATCH /api/v1/entries/{entryRef}/state：set 语义（非 toggle）、严格 bool、空/null body 422、成功 204、双状态合并为一个 edit-tag 请求（repeated a=/r= form 字段）",
        "Action Token 写路径：GET /token 内存缓存、拒绝空/纯空白/x 兼容捷径、edit-tag 成功校验 body=OK",
        "写 401 一次性恢复：清 auth+action token → 重登 → 重取 token → 重试一次；/token 401 同样恢复一次",
        "62 个新增自动化测试（全 Mock），含回归共 120 个通过",
        "真实 Smoke：filters/分页/状态写入全部验证，状态写入后恢复原状（cleanup 验收）"
      ],
      acceptance: "Spec 0004 的 AC1–AC20 全部达成：分支隔离、0002/0003 无回归（120 测试全过）、真实状态字段、view/feed/组合筛选真实生效、cursor 封装与校验、pagination 转换、Action Token 安全缓存、read/starred 真实同步、set 语义、PATCH 契约（204/422）、一次性重试、smoke cleanup、secret 扫描零命中、无越界实现（Category/Mark all read/Batch 未做）。",
      problems: [
        "httpx 0.28.1 AsyncClient 不接受 list-of-tuples 作为 form data（被当作 sync stream → RuntimeError），重复 a=/r= 字段改用 urllib.parse.urlencode + content= 传参",
        "httpx url.path 会 percent-decode，断言线上路径需用 raw_path",
        "Pydantic v2 默认把 1/0 隐式转 bool，需 Field(strict=True) 达到严格 bool 验证"
      ],
      learned: [
        "FreshRSS edit-tag 成功返回 200 + body 'OK'；写响应体也要校验，异常 body → UpstreamError",
        "Action Token 与 Auth Token 同生命周期：任何重登路径必须同步清两者，避免新旧 token 混用",
        "Cursor 携带 filter scope 让“只带 cursor 翻页”可行，同时用显式 view/feedUrl 与 scope 不一致拒绝防混用",
        "set 语义（目标状态而非 toggle）让写 API 幂等，客户端可安全重试"
      ],
      devlog: "../devlog/0004-entry-state-filter-pagination.md"
    },
    {
      id: "0005",
      phaseId: "phase-3",
      name: "Web Shell",
      status: "completed",
      shortGoal: "React app shell + layout",
      goal: "搭建 React 应用外壳与整体布局骨架（导航 / 文章列表 / 阅读区），接入 BFF /api。",
      implemented: [
        "apps/web：pnpm + React 19 + TypeScript + Vite 8（create-vite react-ts 模板，demo 清理，无嵌套 git repo）",
        "Tailwind CSS v4 官方 @tailwindcss/vite plugin（无旧式 postcss/tailwind.config.js）",
        "Vite dev proxy：/api → 127.0.0.1:8000，React 只写相对 /api/v1/*（BFF 零修改、无 CORS）",
        "API client：fetch + ApiError 安全化（cancellation 原样 rethrow 不当网络错误；detail/state 端点故意不存在）",
        "TanStack Query：useFeeds + useEntries（useInfiniteQuery，key 含 view/feedUrl scope，opaque cursor 原样透传）",
        "Zustand：仅 view/selectedFeedUrl/selectedEntryRef，切 view/feed 清空 selection，无 persist",
        "三栏 Web Shell：Sidebar（views + 真实 feeds + loading/error）/ EntryList（loading/error/empty）/ EntryRow（read/starred/publishedAt）/ Load More / ReaderPlaceholder（Query cache 查找，不 fetch detail）",
        "31 个前端自动化测试（Vitest + jsdom + RTL + jest-dom，全 mock fetch），lint 0 警告，production build 成功",
        "真实链路验证：Vite → /api proxy → FastAPI → FreshRSS，真实 feeds/entries 显示，1440/1280/1024 零溢出"
      ],
      acceptance: "Spec 0005 的 AC1–AC22 全部达成：分支隔离、Web 项目可启动、冻结技术栈、相对路径 + Vite proxy（BFF 零修改）、真实 feeds/entries、view/feed 筛选、cursor Load More（真实 nextCursor 不可用因数据 ≤ 20 条，自动测试覆盖）、Query/Zustand 边界、列表各状态、entry 选中不触 detail API、31 测试全绿、lint/build 通过、BFF regression 120 passed、真实链路 smoke + 视觉验证通过。未 commit，停在工作区等待 Review。",
      problems: [
        "pnpm create vite 首次运行卡在交互确认（管道吞掉 stdin），终止后用 printf 'y' 管道重试成功",
        "DOMException 在 Node 运行时不继承 Error：AbortError 检测改用 name 判断而非 instanceof",
        "mock fetch 返回同一 Response 对象时 body 只能读一次，测试改为单次调用断言",
        "测试初稿误用 @testing-library/user-event（未在批准依赖清单），改用 RTL 内置 fireEvent，0 新增依赖"
      ],
      learned: [
        "Server state（TanStack Query）与 UI state（Zustand）的边界是 0005 最重要架构概念：Zustand 不复制任何 server 数据",
        "query key 必须包含 view/feedUrl scope，否则切换筛选返回错误缓存",
        "AbortSignal 透传给 fetch 时，cancellation 必须原样 rethrow 而不是包装成网络错误，否则正常切换筛选会触发 error UI",
        "Vite server.proxy 让浏览器同源请求 /api，开发不需要 CORS，未来 Caddy 同模式替换，React 代码不变"
      ],
      devlog: "../devlog/0005-web-shell.md"
    },
    {
      id: "0006",
      phaseId: "phase-3",
      name: "Reader",
      status: "next",
      shortGoal: "List / read / mark / star interactions",
      goal: "完成阅读闭环：文章列表、阅读正文、标记已读、收藏/取消收藏，先做 Desktop 体验。",
      implemented: [],
      acceptance: "Spec not written yet — 开工时按 PRD §10 先写 spec 再实现。",
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
