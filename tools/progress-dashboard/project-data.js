// LumiRSS Project Board — data source
// ---------------------------------------------------------------
// This file is a web-view SUMMARY of project state.
// If the two ever disagree, docs/README.md + docs/ROADMAP.md win.
//
// How to update (only when a milestone starts or completes):
//   1. Update docs/README.md (the source of truth).
//   2. Update the milestone entry here:
//      - starting:  status "planned" -> "in-progress"
//      - completing: status -> "completed", fill implemented /
//        acceptance / problems / learned, set devlog link, and
//        mark the next milestone "next"; update currentPhaseId /
//        currentMilestoneId / updatedAt.
//   3. Add docs/milestones/<milestone>.md.
// Do NOT rewrite index.html for progress updates.
//
// Milestone status values:
//   "completed" | "next" | "in-progress" | "planned" | "blocked"
// ---------------------------------------------------------------

window.LUMIRSS_PROJECT = {
  updatedAt: "2026-09-03",
  sourceOfTruth: "docs/README.md",
  currentPhaseId: "phase-8",
  currentMilestoneId: "0016",

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
      id: "phase-6",
      num: 6,
      name: "Product Shell",
      label: "Phase 6 — Product Shell（设置中心与自适应外壳）",
      purpose: "完成设置中心（Folo 式 Modal + 声明式设置行 + 9 分类）、侧栏信息架构分组（信息来源/工作区）、三栏拖拽/折叠与移动端底部 Tab——Lumi 的产品骨架。",
      why: "设置与外壳是所有后续功能的承载面；在订阅管理/AI 之前先完成骨架，避免在临时 UI 上继续扩建。",
      milestoneIds: ["0009", "0010", "0011"]
    },
    {
      id: "phase-7",
      num: 7,
      name: "Source Control",
      label: "Phase 7 — Lumi-native Source Control",
      purpose: "让普通用户在 Lumi 内完成订阅增删、分类、OPML、刷新与来源发现（RSSHub 路由搜索/预览/一键订阅）。",
      why: "Lumi 必须成为唯一日常用户界面；FreshRSS/RSSHub 原生页面只保留为高级逃生门。",
      milestoneIds: ["0012", "0013", "0014", "0014a"]
    },
    {
      id: "phase-8",
      num: 8,
      name: "AI",
      label: "Phase 8 — AI Enhancement",
      purpose: "按需单篇摘要、翻译与文章上下文对话（OpenAI-compatible Provider，SQLite 缓存），AI 关闭或失败不影响阅读。",
      why: "AI 是可选增强：用户主动触发、结果归 LumiRSS 自己（存 SQLite），阅读优先于 AI。",
      milestoneIds: ["0015", "0016"]
    },
    {
      id: "phase-9",
      num: 9,
      name: "Completion",
      label: "Phase 9 — Reader Power UX & Unified Settings",
      purpose: "搜索、键盘、批量操作、阅读偏好（字体/字号/行距/宽度）、主题自定义与 FreshRSS/RSSHub/AI 统一设置中心（服务端设置 API 在此落地）。",
      why: "在进入生产部署前完成日常产品体验的收尾。",
      milestoneIds: ["0017"]
    },
    {
      id: "phase-10",
      num: 10,
      name: "Production",
      label: "Phase 10 — Production & Release",
      purpose: "Caddy + HTTPS + 单用户访问保护 + 阿里云 ECS + 备份恢复演练 + 回归/可访问性/性能收尾，发布正式 MVP。",
      why: "最终形态是单台普通 Linux 服务器上的自托管部署：简单、可备份、可恢复。",
      milestoneIds: ["0018", "0019"]
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
        "新建 docs/architecture/README.md 与 docs/README.md"
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
      status: "completed",
      shortGoal: "List / read / mark / star interactions",
      goal: "完成阅读闭环：文章列表、阅读正文、标记已读、收藏/取消收藏，先做 Desktop 体验。",
      implemented: [
        "BFF EntryDetail 最小扩展：contentHtml（上游原始 HTML，明确标注 untrusted，BFF 只搬运不 sanitize；空正文归一化为 null；List 永远不含正文字段）",
        "Web client 新增 getEntry / setEntryState（所有 HTTP 仍集中在 client.ts；204 响应不解析 body；PATCH 无 AbortSignal——写请求不因切换/卸载而中断）",
        "TanStack Query：useEntryDetail（key [entry, entryRef]，enabled，切换选择自动 abort 旧请求）+ useEntryStateMutation（onSuccess 用 variables.entryRef 精确 invalidate + [entries] 前缀，不读当前 selection）",
        "安全渲染边界：DOMPurify（唯一新增 runtime 依赖 3.4.14）HTML-only profile + FORBID_TAGS（form/input/button/textarea/select/option/iframe/object/embed/style/template）+ FORBID_ATTR style，sanitize 后不再二次修改字符串；dangerouslySetInnerHTML 全应用仅 ArticleContent 一处",
        "contentText 纯文本 fallback（pre-wrap，不包装成 HTML）+ 空正文状态（非 Error）",
        "打开原文：safeExternalHttpUrl 纯函数只放行绝对 http/https（javascript:/data:/file:/相对/malformed 一律 null），target=_blank + rel=noopener noreferrer",
        "显式状态按钮：标记已读/未读 + 收藏/取消收藏（set 语义非 toggle，无自动已读；共用一个 mutation，任一 pending 两按钮均 disabled；ReaderHeader 以 entryRef 为 React key 防止旧 mutation UI 泄漏到新文章）",
        "Reader 状态机：no-selection / loading skeleton / success / 404（返回文章列表）/ error（重试）；切文章滚回顶部",
        "97 个前端测试（含 sanitizer 安全测试 + mutation invalidation race）+ 121 个后端测试全绿，lint/build 通过",
        "真实 Smoke：Detail 200 + 富 HTML（含图片/链接）真实渲染；read/star 可逆写入验证后全部恢复原状（cleanup 验收）"
      ],
      acceptance: "Spec 0006 的 AC1–AC28 全部达成：分支隔离、baseline 健康、Detail API 真实工作、enabled query、Server/UI 边界、contentHtml 仅 Detail、DOMPurify 唯一清洗点、sanitizer 安全测试、dangerouslySetInnerHTML 唯一例外、text fallback、empty body、五状态 Reader、安全原文链接、read/star 真实双向同步、set 语义、invalidation 同步、无 optimistic、写失败安全、无自动已读、smoke 状态恢复、97+121 测试全绿、lint/build、真实链路、视觉验证（856px 真实视口 + 1024/1280/1440 近似布局验证无溢出）、仅 dompurify 一个新依赖、无越界。未 commit，停在工作区等待 Review。",
      problems: [
        "feat/0006-reader 分支基于 0004 创建，缺已合并到 main 的 0005——经用户授权 fast-forward 合并后开工",
        "jsdom 元素无 scrollTo 方法，Reader 滚回顶部改用 scrollTop 赋值",
        "DOMPurify 对危险 href 直接移除属性（返回 null），测试断言需容错 ?? ''",
        "0005 旧 Test K（点击不触发 detail API）与 0006 新行为冲突，按 Spec 语义更新为断言点击真实发起 Detail 请求",
        "1440/1280/1024 真实视口 resize 工具不可用（window.resizeTo 被忽略、Playwright 浏览器下载网络受限），改用强制 grid 宽度近似验证布局无溢出 + 856px 真实视口验证"
      ],
      learned: [
        "不可信 HTML 边界：BFF 运输 ≠ 可信，DOMPurify 是唯一清洗点，sanitize 后绝不再改字符串",
        "Query 与 Mutation 的 cancellation 区分：GET 用 AbortSignal 快速切换，PATCH 不建 AbortController 让写请求自然完成",
        "mutation onSuccess 必须用 variables.entryRef 而非当前 selection——完成前 selection 可能已切换，读 Zustand 会 invalidate 错误的 key",
        "React key=entryRef 重挂载是最小的跨 Entry mutation UI 泄漏防护，无需 mutation.reset 或状态管理层",
        "204 No Content 响应不能 response.json()，client 需要一条不解析响应体的请求路径"
      ],
      devlog: "../devlog/0006-reader.md"
    },
    {
      id: "0007",
      phaseId: "phase-3",
      name: "Mobile + PWA",
      status: "completed",
      shortGoal: "Mobile reading flow + basic PWA",
      goal: "移动端“列表 → 详情 → 返回”的纵向阅读流，加上基础 PWA（manifest / 图标 / standalone 启动）。",
      implemented: [
        "同一棵组件树的响应式布局：<1024px Mobile Header + 单主内容区 + 导航抽屉，≥1024px 三栏桌面不变（纯 CSS media query，无 JS 宽度探测）",
        "导航抽屉复用同一份 Sidebar（onNavigate 显式关闭；backdrop / ✕ / Escape；非 modal <aside> landmark，无 aria-modal）",
        "手机 list↔reader 切换由既有 selectedEntryRef 驱动，返回复用 Query cache 不 reload",
        "≥44px 触摸目标、手机标题 wrap、紧凑 metadata、正文移动端 padding",
        "viewport-fit=cover + 四方向 safe-area CSS variables",
        "静态 manifest.webmanifest（standalone）+ 本地生成 192/512/maskable/apple-touch 图标",
        "无 Service Worker / 无离线缓存 / 零新增依赖（installability ≠ offline）",
        "24 个新增自动测试（导航/Reader 流/PWA 验证），前端 121 全绿，BFF 121 全绿零修改"
      ],
      acceptance: "AC1–AC28：核心全 PASS（含真实浏览器 856px 移动布局全交互、可逆 read/star smoke、31 图文章零横向 overflow、manifest+icons HTTP 200）；OS 级真实安装为 USER/MANUAL VERIFICATION；390/430/768/1024+/1440 真实视口截图 UNVERIFIED（浏览器 resize 被忽略），布局模式由 856px 真实验证 + CSS 规则检查 + 全量回归覆盖。",
      problems: [
        "playwright MCP 缺浏览器二进制、browser-use 无法 POST 本机、手工转录长 base64 出错（FNV 校验拦截）",
        "Tailwind v4 不生成 lg:max-[1100px] 叠加变体（按 Spec 预案退化为统一列宽）",
        "jsdom 无 crypto.subtle；不支持真实 resize；测试需处理 drawer 新 observer 的 stale-on-mount 后台 refetch"
      ],
      learned: [
        "PWA installability ≠ offline：manifest + secure context 已足够，Service Worker 是离线能力而非安装前提",
        "同一棵组件树 + CSS 决定布局：复用 Sidebar/Reader/EntryList，只新增 MobileHeader/Drawer 两个小组件和 mobileSidebarOpen 一个状态",
        "本机无任何 CLI rasterizer 时，纯 Node stdlib（zlib + 手写 PNG 编码器 + supersampling 抗锯齿）可以零依赖生成精确尺寸图标",
        "远程浏览器 canvas 导出 → base64 经上下文转录不可靠；跨系统搬大数据必须带长度+哈希双校验或改用本地生成",
        "jsdom 只能断言 DOM/class 语义，真实视觉必须真浏览器（smoke 用 a11y snapshot + overflow 度量 + 截图三重验证）"
      ],
      devlog: "../devlog/0007-mobile-pwa.md"
    },
    {
      id: "0008",
      phaseId: "phase-4",
      name: "RSSHub Integration",
      status: "completed",
      shortGoal: "Non-RSS → RSSHub → FreshRSS real link",
      goal: "证明至少一条真实链路：非 RSS 网站 → RSSHub → FreshRSS → LumiRSS。只解决真实需要 RSSHub 的订阅源，不做 Route 搜索/编辑器。",
      implemented: [
        "docker-compose.yml 新增最小 rsshub service：官方镜像 digest 固定（diygod/rsshub@sha256:387fd32e…，2026-08-28 官方构建），127.0.0.1:1200 仅本机，/healthz healthcheck（含 start_period），NODE_ENV=production + CACHE_TYPE=memory",
        "无 Redis / 无 Browserless / 无 Chromium：单用户单实例场景官方最小部署形态",
        "三层健康验证：container running → /healthz 200 ok → 真实 Route 200（/ithome/ranking/24h：网页 HTML → RSS 2.0，12 items，requireConfig=false / requirePuppeteer=false）",
        "Docker service DNS 验证：FreshRSS 容器内 rsshub 解析成功；订阅 URL 用 http://rsshub:1200/<route>（人工 checkpoint，不新增 Feed CRUD）",
        "BFF End-to-End：/api/v1/feeds 出现 RSSHub Feed → /entries?feedUrl= 返回 12 条（read/starred 正常）→ Detail 200（contentText 449 字符 + contentHtml 918 字符）；BFF/Web 零代码修改",
        "Web 真实浏览器 smoke：All 列表混排无感知差异 → 点击文章 Reader 完整渲染 → Sidebar 选 Feed 专项列表（12 条）；Web 不知道 Feed 来自 RSSHub",
        "Failure isolation：stop rsshub 后 BFF /health/live 200、3 feeds 正常、原生 RSS 3 条正常、已存 RSSHub 12 条照常可读（含 Detail 全文）；restart 后 health + Route 恢复",
        "资源观测：idle CPU ≈0%，内存 ≈253 MiB（对比 freshrss 73 MiB）",
        "IT之家 Demo 订阅经用户确认保留"
      ],
      acceptance: "Spec 0008 的 AC1–AC26 全部达成：分支隔离、baseline 健康（BFF 121 / Web 121 + lint + build）、官方镜像 + digest 固定、最小服务、loopback 端口、healthz 真实 200 + healthy、真实 Route 有效 RSS + 12 items、非 RSS 来源证明、service DNS 订阅 URL、FreshRSS 成功抓取、BFF feeds/entries/detail 全验证、Web Reader smoke、无 RSSHub-specific code（bff/web diff = 0）、failure isolation + recovery、数据安全（无 down -v / volume rm）、无 Secret、零新依赖、回归全绿（BFF 121 / Web 121）、资源记录、Demo 保留（用户批准）、无越界。未 commit，停在工作区等待 Review。",
      problems: [
        "Docker Hub Registry API 直连不可达（已知网络限制），但 daemon 代理仍生效，docker pull 一次成功",
        "browser-use click 工具对列表项点击超时，改用 evaluate_script 直接触发 click 完成 Web smoke；截图能力不可用（浏览器视图不可见，同 0006/0007 工具限制），以 a11y snapshot 作为验证证据",
        "/tmp 沙箱只读导致 probe 临时文件无法删除（不在仓库内，无影响）"
      ],
      learned: [
        "官方 RSSHub 最小部署 = 单服务 + CACHE_TYPE:memory：Redis/Browserless 只是多实例缓存和浏览器 Route 的可选依赖",
        "Image pin 用 docker image inspect 的 RepoDigests（@sha256:…），比日期 tag 更不可漂移",
        "三层健康概念：container running ≠ /healthz 200 ≠ 具体 Route 正常（Route 还依赖上游网站），验收要逐层验证",
        "宿主机 127.0.0.1:1200 与容器内 rsshub:1200 是同一服务的两个视角：订阅 URL 必须用 service DNS，因为 FreshRSS 容器里的 localhost 是它自己",
        "Failure isolation 的根源是架构分层：RSSHub 只在生成 Feed 时参与，阅读链路永远走 FreshRSS，所以 RSSHub 宕机只影响增量不影响存量",
        "浏览器自动化工具超时时用 evaluate_script 直接触发 DOM click 是可靠的降级手段"
      ],
      devlog: "../devlog/0008-rsshub-source-expansion.md"
    },
    {
      id: "0009",
      phaseId: "phase-6",
      name: "UI Reboot & Reference Lab",
      status: "completed",
      shortGoal: "Design system + responsive shell, zero API change",
      goal: "用统一的 Lumi Mist 主题（semantic tokens、Light/Dark/System）、共享 UI primitives 和精化的 Sidebar/Timeline/Reader 替换临时视觉外壳。参考基线：Folo（交互/密度）+ OrigRead Desktop（设置/阅读工具）；行为、API 与数据契约零变更。原 0009 AI Summary 移至 0012。",
      implemented: [
        "Gate 0：仓库/代码/文档全量核验；参考仓库钉 SHA（Folo dev 78f6bd1b / OrigRead 18d3281 / OrigRead-Desktop 8b59bcb4）；许可证决策 AGPL-3.0-only；Folo 实机审计；v6 文档基线",
        "Gate 1：styles/tokens.css（圆角/动效/z-index/scrollbar/reduced-motion）+ styles/themes.css（Lumi Mist Light/Dark + Reader sepia/warm 变体）；三态主题逻辑（localStorage 持久化 + FOUC 防闪烁）；lucide-react@1.34.0（ISC，用户批准）；11 个 UI primitives + dev-only playground（生产 bundle 零包含）",
        "Gate 2：App Shell Grid（240/400/minmax(0,1fr) + pane 分层）；Sidebar Folo 密度（32px 行 + lucide 图标 + 确定性分类色圆点）；Timeline 两级行层级（字重区分已读/未读，不只靠颜色）",
        "Gate 3：Reader 重建（图标工具栏 + 27px 标题 + 46rem 正文宽 + 17px/1.75 排版）；Reader 独立背景钩子（--lumi-reader-bg + data-reader 变体，App/Reader 主题分离实测验证）",
        "Gate 4：Settings 壳（Appearance 真实可用：主题模式 + 阅读背景；其余分组明确标注 planned，无假控件）；统一 6px scrollbar；视口矩阵 12 截图零溢出零 console error"
      ],
      acceptance: "AC1–AC27 全部达成：BFF 零变化（git diff 空）；硬编码色全量清零；162 前端测试全绿（121 既有 + 41 新增，零回归）+ BFF 121 通过；Lumi Mist 双主题 + System/Light/Dark 三态 + 刷新持久化 + reduced-motion；primitives 全部可访问（focus trap/Escape/aria）；5 尺寸 × 双主题零横向溢出；真实 FreshRSS 数据下可逆 read/star smoke + 零前端直连上游请求；无 icons/mgc、无私人截图入库。未 commit，停在待人工 Review。",
      problems: [
        "截图工具两轮修复：browser-use 需面板可见 + playwright MCP 缺系统 Chrome → 免 sudo 方案（本地 chromium + 用户目录库/字体 + LD_LIBRARY_PATH）打通，后经用户 sudo 授权永久化（系统 Chrome 152 + 系统库 + Noto CJK）",
        "Playwright 版本错位：npx 缓存 playwright 期望 chromium-1237，实际下载 1234 → 脚本显式 executablePath 解决",
        "lucide-react registry 缓存延迟：latest 1.35.0 未同步，锁定 1.34.0（同为 ISC）",
        "React Compiler 对 render-prop（Popover/Menu trigger）与组件+导出混存文件（SettingsDialog）报 fast-refresh warning（非错误）：后者已抽 lib/reader-bg.ts 规范化"
      ],
      learned: [
        "旧 CSS 变量别名策略：--bg/--surface 等指向 lumi token，既有组件零改动即获双主题，迁移期平滑过渡",
        "Folo 主题机制可复用：html[data-theme] + 语义变量 + oklab 低透明度选中态，实现成本低于自创",
        "未读状态用字重 + 圆点双信号（非仅颜色），测试断言从 aria-label 转为类名/结构断言",
        "data-reader 独立背景钩子：任意元素挂属性切换 --lumi-reader-bg，App/Reader 主题分离的最小实现",
        "免 sudo 依赖安装模式：apt-get download + dpkg -x 到用户目录 + LD_LIBRARY_PATH（后续已永久化为系统安装）"
      ],
      devlog: "../devlog/0009-ui-reboot-reference-lab.md"
    },
    {
      id: "0010",
      phaseId: "phase-6",
      name: "Settings Center & Adaptive Shell (+0010a)",
      status: "completed",
      shortGoal: "Folo-style settings + adaptive panes + mobile tabs",
      goal: "Folo 式设置中心（声明式设置行 + 9 分类：5 真实可用 + 4 planned）、侧栏信息架构分组（信息来源/工作区，Phase 2 项可见禁用）、三栏拖拽/折叠/持久化、移动端底部 Tab——全部纯前端（localStorage），BFF 零变化。原 0010 Unified Subscription Center 顺延为 0011。",
      implemented: [
        "Gate A：app-settings store（类型化模型 + localStorage 单 key + 旧 key 迁移）+ SettingItem 声明式渲染器（五型）+ SettingsModal 框架（左导航 9 分类，Folo 实测尺寸）；修复 Dialog 遮罩点击关闭 bug（0009 遗留）",
        "Gate B：快捷键 j/k/u/s（Query cache key 修复）+ 速查表页；数据控制（清缓存/重置真实可用）+ 关于页；4 个 planned 页（订阅 0011/0012、AI 0013/0014、账户与服务、工作区 Phase 2）；未读圆点开关真实生效",
        "Gate C：Sidebar 信息架构分组（信息来源/工作区，9 个 Phase 2 项可见禁用+徽标）+ PaneSeparator（拖拽/键盘/双击重置 + aria）+ 折叠/展开 + localStorage 持久化；修复分隔条高度塌陷 bug",
        "Gate D：<768px 底部 Tab（时间线/收藏/设置，Reader 时隐藏）+ 设置移动端全屏化 + 看板修订（内容顺延 + Lumi Mist 样式统一）+ 文档修订（PRD v6.1/ROADMAP/PROJECT_STATE/AGENTS/README）",
        "0010a Gate E：修复移动端设置布局 bug（Dialog+chip 条方案重设计为 Folo 移动端模式：全屏分组列表 → push 子页）+ 分类 9→13（翻译/文章过滤/RSSHub/备份与恢复）+ 通用页 4 项（已读变暗/按日期分组/启动仅未读/实验性滚动已读）",
        "0010a Gate F：外观补全（accent 色板/全局字号/UI 字体/减少动效）+ 阅读样式 P0（字体族四档/背景色板+自定义 hex+WCAG 自适应文字/段距/两端对齐/图片三模式）+ P1（自定义 CSS .lumi-reader 前缀注入 + 5 套排版预设+派生导入导出）+ OrigRead 四页复刻（翻译 Provider 卡片/过滤规则+显示层过滤/RSSHub 16 内置实例/加密配置备份 Web Crypto）",
        "0010a Gate G：加密备份往返实测 16/16 + 视口矩阵 10/10 + 文档 v6.2（0011 插入，0012-0018 顺延）+ 阅读器样式调研归档（reader-style-survey.md）"
      ],
      acceptance: "达成：244 前端测试全绿（0010a 后）、lint 0 errors、build 成功、BFF 零变化；备份往返 16/16、视口矩阵 10/10、accent/预设/自定义 CSS/自定义背景/显示层过滤全部真实浏览器实测通过。",
      problems: [
        "Query cache key 不匹配：快捷键模块构造 ['entries', {view}] 而 useEntries 实际用 {view, feedUrl}——单测预置缓存用同一错误 key 假绿，真实浏览器实测暴露后修复",
        "PaneSeparator 高度塌陷：hidden lg:block wrapper 在 flex-row 中不拉伸导致分隔条 height=0 完全不可点（jsdom 无布局测不出）——wrapper 改 lg:flex + self-stretch 修复",
        "「侧栏隐藏已读」中途纠偏：本想存偏好暂不生效，识别出违反诚实原则（假控件）——改为 planned·0012（需要 feeds unreadCount 契约）",
        "0010a Gate D 移动端设置布局损坏（容器缺 max-md:flex-col，内容区被挤出视口）：根因是 Gate D 验证只测 isVisible 没查视觉——Gate E 按 Folo 移动端模式重设计并全部实测布局",
        "CSS 前缀解析器嵌套配对 bug：indexOf('}') 命中嵌套块内层 } 导致 @media 整段拒绝——改为深度配对 matchingClose",
        "无密钥备份恢复清空本机 API Key（违反 OrigRead「无密钥备份不清空凭据」语义）：加密往返实测发现——修复为仅当备份携带且解密成功才替换"
      ],
      learned: [
        "声明式设置行（Folo setting-builder 模式）：新增设置=加一行数据，视觉天然一致",
        "真实浏览器实测是单测的必要补充：cache key 不匹配与分隔条高度塌陷都是 jsdom 测不出、实测立即暴露的",
        "localStorage 单 key + 逐字段归一化：损坏 JSON/非法值回退默认不抛错，旧 key 首次加载自动迁移",
        "移动端设置用「分组列表 → push 子页」而非 Modal（Folo mobile 同款）：桌面/移动共享 CategoryPage 组件与 store，仅外壳不同",
        "自托管阅读器自定义 CSS 是刚需（Miniflux/CommaFeed/FreshRSS 三先例）：作用域限定 .lumi-reader 前缀注入 + 解析失败整段拒绝",
        "主题 = CSS 变量快照（TTRSS/NetNewsWire 先例）：预设切换即批量写变量，派生+导入导出形成分享生态雏形（Web 端无先例——0011 差异化）",
        "真实浏览器实测再次证明不可替代：布局 bug、CSS 解析 bug、备份语义 bug 三个都是单测测不出、实测立即暴露"
      ],
      devlog: "../devlog/0010-settings-center-adaptive-shell.md"
    },
    {
      id: "0011",
      phaseId: "phase-6",
      name: "Mobile UI Five-Screen Alignment",
      status: "completed",
      shortGoal: "Mobile 一级页面 · 抽屉导航 · 底部导航岛 · list↔Reader 契约",
      goal: "移动端信息架构一级页面（首页/订阅/搜索/收藏）+ 导航抽屉 + 底部导航岛；列表 ↔ 全屏 Reader 出行契约（0014a 收口补齐收藏 section 让位）。",
      implemented: ["移动端一级页面与卡片化列表、主导航（0007 drawer 升级 modal）、底部四 tab、移动 Reader 全屏语义（0011 Gate 1–4）"],
      acceptance: "已完成（见 docs/milestones/0011-mobile-ui-five-screen-alignment.md）",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0012",
      phaseId: "phase-7",
      name: "Reader Style Deep Customization",
      status: "completed",
      shortGoal: "字体导入 + 中文排版 + 主题包 + 代码高亮",
      goal: "阅读深度自定义：字体导入（FontFace + IndexedDB）、中文排版（首行缩进/标点悬挂/简繁/CJK 阅读时长）、主题包 .lumitheme 导入导出、代码高亮（Shiki）、Aa 快速面板。",
      implemented: ["Depth customization completed（见 docs/milestones/0012-reader-style-deep-customization.md）"],
      acceptance: "已完成（见 docs/milestones/0012-reader-style-deep-customization.md）",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0013",
      phaseId: "phase-7",
      name: "Unified Subscription Center",
      status: "completed",
      shortGoal: "Feed CRUD + categories + OPML inside Lumi",
      goal: "普通用户在 Lumi 内完成订阅增删/分类/重命名、OPML 导入（preview→confirm→merge）与导出、FreshRSS 实时连接状态（经 FreshRSSControlAdapter 控制平面）。",
      implemented: ["SubscriptionsPage 管理视角、OPML import/export、FreshRSS 状态/逃生入口（可信 URL 才渲染）"],
      acceptance: "已完成（见 docs/milestones/0013-unified-subscription-center.md）",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0014",
      phaseId: "phase-7",
      name: "Source Discovery & RSSHub Integration",
      status: "completed",
      shortGoal: "URL → RSS/Atom 发现 · RSSHub 路由 → 预览 → 订阅",
      goal: "网站 → RSS/Atom 发现（rel=alternate + 常见端点探测）与 RSSHub 目录/参数/预览，AddSourceDialog 三模式单表面，全部经 BFF 代理（server-side RSSHUB_BASE_URL）。",
      implemented: ["source-discovery + rsshub 服务（396 新增 BFF 用例、catalog 14 条实测校准）、AddSourceDialog（RSS/网站/RSSHub）、preview→subscribe 复用 0013 管道"],
      acceptance: "已完成（见 docs/milestones/0014-source-discovery-rsshub-integration.md）；浏览器实机验收归 0014a",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0014a",
      phaseId: "phase-7",
      name: "UI Acceptance & Navigation Consistency",
      status: "completed",
      shortGoal: "桌面 Add Source · 移动 Reader 一致性 · 设置真实性 · Playwright 验收",
      goal: "关闭 0014 真实产品验收缺口：桌面「添加来源」入口（复用 AddSourceDialog）、移动收藏→全屏 Reader（section 让位 + back 原列表）、FreshRSS/RSSHub 设置事实对齐（无 stale planned·0013）、真实 Playwright 桌面/移动验收；并修订 0015–0019 路线（用户已批准）。",
      implemented: [
        "Sidebar 桌面上下文「添加来源」入口（复用 AddSourceDialog，无第二套订阅逻辑）；订阅管理页新增 导出 OPML（共享 useOpmlExportFlow）",
        "App 移动布局契约：收藏/搜索/订阅 section 在 Reader 打开时 max-lg:hidden 让位——任何文章列表点击均进入全屏 Reader，back 返回原列表（section/view/scope 不变）",
        "设置事实对齐：清除 stale planned·0013（账户与服务 FreshRSS 状态 / 备份页 OPML / 侧栏隐藏已读归属）；FreshRSS 维护操作 + RSSHub 运营中心 → planned·0018（诚实区分 0014 已实现能力与 0018 运营能力）",
        "0015–0019 路线修订：lumi.sqlite Lumi-owned 真源、0017 连续式 Reader 控件、0018 RSSHub Control Center + FreshRSS 运营 + WebDAV 备份/恢复（用户批准）"
      ],
      acceptance: "通过：Web 476/36 files、BFF 367、lint 0 errors、build ✓；真实 Playwright 桌面 1440×900 + 移动 390×844 全流程验收通过（见 docs/milestones/0014a-ui-acceptance-navigation.md）。",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0015",
      phaseId: "phase-8",
      name: "AI Foundation, Summary & Lumi SQLite Foundation",
      status: "completed",
      shortGoal: "On-demand summary + lumi.sqlite foundation",
      goal: "激活 Lumi-owned 持久层 lumi.sqlite（迁移/模式策略先行）：AI 结果缓存、provider/model 元数据、prompt 版本、内容哈希、生成状态、需持久化的服务端设置、备份元数据；OpenAI-compatible provider + 按需摘要；FreshRSS 仍为 RSS-domain 唯一真源（不影子复制 feeds/entries/read/starred/订阅/分类）。",
      implemented: [
        "lumi.sqlite：stdlib-only 版本化迁移（schema v1，schema_migrations 记账，失败回滚）",
        "lumi_settings：allow-list 非机密 AI 设置（provider/base_url/model/summary_language）",
        "ai_summaries：cache identity（entryRef+contentHash+provider+model+promptVersion+language）+ 状态/失败元数据",
        "OpenAI-compatible provider：httpx 直连 chat/completions，key 仅服务端 env，稳定错误映射",
        "SummaryService：normalize(12k 上限) + SHA-256 contentHash + summary-v1 prompt + 注入边界 + 单进程锁防重复生成",
        "API：GET/PUT /api/v1/settings/ai；GET /api/v1/entries/{ref}/summary（零生成）；POST 显式生成",
        "Web：AI 设置页（无 key 输入框/configured banner）+ Reader 摘要卡（8 态 + 缓存徽标 + 重试）",
        "Playwright 桌面/移动验收 + Vision 视觉 QA PASS（live smoke SKIPPED 无 key）"
      ],
      acceptance: "421 BFF + 486 Web 全绿；lint 3 存量 warnings；build 通过；Playwright desktop/mobile 通过；Vision PASS。",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0016",
      phaseId: "phase-8",
      name: "Translation & AI Conversation",
      status: "completed",
      shortGoal: "Title/body translation + article-scoped AI chat",
      goal: "标题/正文翻译与双语阅读、翻译缓存、文章上下文 AI 对话（共享 0015 AI foundation）、桌面右侧面板 + 移动全屏 Sheet；依赖 0015。",
      implemented: [
        "AIProvider.complete(messages)：通用 chat/completions 入口（summarize 委托），单传输单错误映射",
        "ai.translation_language 设置（zh-CN/en，默认 zh-CN）+ AI 设置页翻译语言选择",
        "migration 0002：ai_translations（cache identity 含 targetLanguage）+ ai_conversations/ai_conversation_messages",
        "TranslationService：标题+正文单次调用翻译，分隔标记解析（缺失时优雅降级），缓存/失败/重试全状态",
        "API：GET/POST /api/v1/entries/{ref}/translation；GET conversation + POST conversation/messages（question 4k 上限）",
        "Web：Reader 原文/译文分段切换（译文纯文本视图）+ AI 对话右侧面板（移动全屏 Sheet，历史持久化/重试/Escape）",
        "桌面/移动浏览器验收 + Vision 视觉 QA PASS（live AI smoke SKIPPED 无 key）"
      ],
      acceptance: "462 BFF + 499 Web 全绿；lint 3 存量 warnings；build 通过；桌面 1440×900 + 移动 390×844 行为验收通过；Vision PASS。",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0017",
      phaseId: "phase-9",
      name: "Reader Power UX & Unified Settings",
      status: "next",
      shortGoal: "Continuous reader controls (WYSIWYG) + unified settings",
      goal: "微信读书式连续阅读定制（bounded 连续值，非离散预设）：字号（滑杆 A-/A+）、行高、段落间距、内容/页宽、左右页边距——即时生效（WYSIWYG）且持久化数值；继承既有 Reader 定制（主题/字体/中文排版/代码/图片/对齐/首行缩进/减动效/重置默认）；统一设置服务端化（0015 lumi.sqlite 持久化，保留本地即时响应）；具体 min/max/default 以视觉测试与排版约束选定。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0018",
      phaseId: "phase-10",
      name: "Production, Operations & Backup",
      status: "planned",
      shortGoal: "RSSHub Control Center · FreshRSS operations · WebDAV backup/restore",
      goal: "三大运营面：A) RSSHub Control Center（schema 驱动类型化 allow-list 配置；secrets 只写不读回；restartRequired 展示；无任意环境变量编辑器/任意 shell/无限制 Docker socket）；B) FreshRSS Operations（诊断/健康/备份/高级逃生入口；不重建 FreshRSS UI）；C) WebDAV 备份/恢复（manifest + FreshRSS 导出 + lumi.sqlite + 服务配置 + RSSHub 配置 + checksums；secrets 加密或排除；多步非破坏恢复流程）。另含生产 Compose/Caddy/TLS/持久卷/健康就绪/日志脱敏/升级回滚/资源限制/灾难恢复演练。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    },
    {
      id: "0019",
      phaseId: "phase-10",
      name: "MVP Stabilization & Release",
      status: "planned",
      shortGoal: "Regression + responsive matrix + drills + release",
      goal: "MVP 冻结：全量回归、桌面/移动响应式矩阵、Playwright 流程、可访问性、安全、性能预算、空/加载/错误态、备份恢复演练、升级回滚演练、许可证审查、operator 文档、release notes 与 MVP release；不再新增主要产品功能。",
      implemented: [],
      acceptance: "Not started yet.",
      problems: [],
      learned: [],
      devlog: null
    }
  ]
};
