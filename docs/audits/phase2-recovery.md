# Phase 2 Recovery — Issue Ledger

> 单一事实账本。每项必须有：症状、根因、复现、受影响文件、数据风险、修复方案、
> 回归测试、修复 commit、local/compose/production 三层状态、证据。
> 状态机：`confirmed → implementing → locally_verified → compose_verified → production_verified`
>（无法在本环境关闭的项为 `externally_blocked`）。
> 旧测试绿灯（BFF 778 / Web 669）只是回归基线，不构成 Phase 2 完成证据。

## Baseline（2026-09-13 记录）

- `origin/main` = `7d1191b7b6033988b345bcbec93f587dc737cec6`（PR #43 Phase 2 integration，审计基线一致）。
- 修复分支：`phase2/recovery-20260913`（自 `7d1191b` 创建）。
- 生产（rss.oouo.top / 47.100.64.202）：据 2026-09-13 部署记录为 `7d1191b`，migration v15，
  备份 20260913-012436 存在，回滚快照已修正指向 `872035a`。**本会话无 SSH 密钥，直接核验 = 外部阻塞**
  （BLOCKER-E1）。Phase 2 用户数据已在生产：所有 schema 修复必须 forward-only migration。
- 本地资源：WSL2，7.6GB RAM（可用 ~4.4GB），20 核，磁盘 924GB。dev 容器 freshrss/rsshub 运行中。
- 环境陷阱：WSL2 走 fake-IP DNS（198.18.0.0/15），真实外网抓取会被 SSRF 防线拒绝（如实，
  测试用本地受控源）；HuggingFace 下载可达（走代理）。

### Baseline 验证记录

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| BFF pytest | `cd services/bff && uv run pytest -q` | 778 passed（44.9s）✓ |
| BFF ruff | `cd services/bff && uv run ruff check src tests scripts` | clean ✓ |
| Web vitest | `cd apps/web && pnpm test` | 669 passed ✓（需先 `pnpm install`，本地 node_modules 缺 cytoscape） |
| Web lint | `cd apps/web && pnpm lint` | 15 warnings / 0 errors ✓ |
| Web build | `cd apps/web && pnpm build` | OK，bundle guard OK（initial 659kB raw/208kB gzip）✓ |

注：main 上新克隆/未重装依赖的环境会因 node_modules 缺 `cytoscape` 导致 1 个 suite 收集失败
（`GraphPage.tsx`），package.json 已正确声明——环境问题，非仓库缺陷。

## 外部阻塞

### BLOCKER-E1 — 生产直接核验不可用

- 症状：本会话 SSH（root@47.100.64.202）publickey denied；无法读取生产 SHA/迁移版本/表行数。
- 已知替代证据：2026-09-13 部署会话记录（生产=7d1191b、migration v15、备份 20260913-012436、
  回滚快照 872035a）。
- 影响范围：production_verified 状态判定；生产 smoke；生产数据审计。
- 解除条件：用户提供 SSH 密钥，或用户在生产执行核验命令并回传输出。
- 当前处置：本地完成全部实现/测试/release candidate；不执行任何生产写操作。

## P0 Issues

### P0-01 — Read-later 是加载后本地过滤，不是服务端列表 — `confirmed`

- 症状：`view=read-later` 实际请求普通 `view=all` 只过滤当前已加载 timeline；旧稍后读项在翻到对应页前不出现；跨设备同步只做一次；服务端失败后乐观状态不回滚。
- 根因：客户端本地过滤实现（`apps/web/src/lib/read-later.ts`、`apps/web/src/store/read-later.ts`、`apps/web/src/components/EntryList.tsx`），服务端无 reserved workspace 列表。
- 复现：保存首屏外旧文章为 read-later → 刷新/换客户端 → 不出现。
- 受影响文件：上述 + `services/bff/src/lumirss/routers/workspaces.py`。
- 数据风险：用户以为已存的稍后读丢失（实际存在 FreshRSS starred/标记，但列表不可见）。
- 修复方案：服务端驱动、可分页/排序的 read-later 查询；客户端删除本地过滤；乐观失败回滚+错误 UI。
- 回归测试：旧稍后读超过首屏、跨设备刷新、服务端失败回滚。
- 修复 commit / 状态：（待填）
- Owner：主 Agent（Gate 1）。

### P0-02 — ItemRef / Source Registry 只真正解析 bookmark — `confirmed`

- 症状：clip、snapshot、Obsidian 等 ItemRef 不能统一解析 → workspace、tag、Agent、统一视图“内容不存在/未知类型/不可打开”。
- 根因：`services/bff/src/lumirss/library.py`、`deps.py` 只实现 bookmark resolve；`apps/web/src/components/UnifiedContentCard.tsx` 无对应打开目标。
- 复现：把 clip/snapshot/obsidian note 加入 workspace/tag → 打开失败。
- 受影响文件：`library.py`、`deps.py`、`itemref.py`、`UnifiedContentCard.tsx`。
- 数据风险：引用悬挂；tag/graph 引用不存在内容。
- 修复方案：唯一 ItemRef parser/normalizer/resolver registry，覆盖 RSS/bookmark/clip/snapshot/obsidian；existence validation + batch resolve + 打开目标（ADR-0021）。
- 回归测试：各 kind resolve、失效引用、batch、打开目标一致性。
- Owner：主 Agent（Gate 1 基础）。

### P0-03 — Clipping 信任浏览器提交的 HTML — `confirmed`

- 症状：服务端抓原始 HTML 后，浏览器提取/清理并把客户端控制的 `contentHtml` 写回；服务端只查非空+大小；多步写入无完整事务。
- 根因：信任边界放在客户端。
- 复现：直接 POST 任意 `<script>` HTML 到 clip API → 被存储。
- 受影响文件：`clip_fetch.py`、`library_clips.py`、`routers/clips.py`、`http_fetch.py`。
- 数据风险：存储型 XSS 绕过 DOMPurify 前置假设；孤儿数据。
- 修复方案：`URL → 服务端安全抓取 → 服务端提取 → 服务端 sanitize → 持久化 → 安全展示`；事务化写入。
- 回归测试：恶意 HTML/script/event handler/危险 URL/CSS；事务补偿。
- Owner：IMPL-BE-1（Gate 2）。

### P0-04 — Snapshot 在生产镜像中不可用且命令错误 — `confirmed`

- 症状：生产镜像无 Monolith；调用缺正确输出参数；`-C 1` 被当超时（实为 cookie 文件）；原始 URL 未持久化；dedupe 布尔语义反转；引用计费重复；删除留孤儿 item；文件/DB 不原子；子资源 SSRF 未受控。
- 受影响文件：`services/bff/Dockerfile`、`docker-compose.prod.yml`、`snapshots.py`、`library_assets.py`。
- 复现：生产镜像内运行 snapshot 创建 → monolith: command not found / 文件为空。
- 数据风险：配额计费错误、孤儿文件、快照不可离线打开。
- 修复方案：固定版本+checksum 安装 Monolith；按真实 `--help` 构造命令；真实离线打开验证；原子写入；引用计数删除；子资源 SSRF 策略（无法安全约束则禁用远程 snapshot 并如实标注）。
- 回归测试：生产镜像内真实命令测试 + 恶意子资源测试。
- Owner：IMPL-BE-1（Gate 2）。

### P0-05 — API Source 的 feed 地址、Atom 与缓存逻辑不成立 — `confirmed`

- 症状：默认 Atom base 为 BFF 容器本机地址（FreshRSS 容器不可达）；Caddy 不代理 `/feeds/*`；`updated` 每请求取当前时间 → ETag 每次变化；entry 缺 `updated` 等 Atom 元数据；上游失败无 last-known-success；删除 source 忽略退订失败留死订阅。
- 受影响文件：`routers/api_sources.py`、`api_sources.py`、`docker-compose.prod.yml`、`.env.prod.example`、Caddy 配置。
- 复现：创建 API source → FreshRSS 订阅失败；连续 GET 观察变化；断上游观察无 stale。
- 数据风险：死订阅、缓存永远失效、数据不新鲜不可知。
- 修复方案：双 base URL 契约（容器内/公网）+ Compose/Caddy/env 同步；Atom 合规（RFC 4287）；稳定 ETag/304；last-known-success + stale/error 状态；幂等 subscribe/unsubscribe/delete。
- 回归测试：RFC 4287 结构验证、ETag 稳定性、stale fallback、退订失败保留配置。
- Owner：IMPL-BE-1（Gate 3）。

### P0-06 — Mail/Newsletter/Digest 多条主链路只是外壳 — `confirmed`

- 审计结论（BE-2 审计，全部 file:line 已核，13/13 证实）：
  - (a) `main.py:61-145` 无 DigestScheduler；`routers/mail.py:228` `_ = (DigestScheduler,)` 是死元组+假注释。
  - (b) `MailSection.tsx:309-312` `sendNow()` 固定 `mutate([])`；`g6-ui.test.tsx:287-294` 把空数组断言进测试。
  - (c) `routers/mail.py:177-208` 硬编码 `[:20]`，不读 `source`/`limitCount`；`enabled/hour` 只有无人调用的 `DigestScheduler.maybe_send` 读。
  - (d) `mail_imap.py:132` `get_list` 缺 `await` → 协程对象传入 ingest → `AttributeError`；每次 IMAP 轮询必崩。
  - (e) `ImapAdapter`/`load_imap_config`/`save_imap_config` 无任何 router/lifespan 引用；`errors.py:100,252` 的映射不可达。
  - (f) `SessionAuthMiddleware` 最外层（`main.py:165`），`middleware.py:309-312` 对所有 `/api/*` 要求 session cookie；webhook bearer 校验（`mail.py:98-102`）永远走不到；basic 模式下 Caddy basic_auth + InternalToken 也挡——**机器对机器投递通路完全不存在**。
  - (g) `MailSection.tsx:104-213` 把 webhook 叫"收信地址"，复制的是相对 URL 无 origin。
  - (h) FreshRSS 自动订阅只存在于 `mail_bridge.py:8-10` docstring，无代码。
  - (i) Atom 违反 RFC 4287：feed `updated` 可空（`mail.py:135`）、entry 无 `updated`/`author`、feed 无 `link`。
  - (j) `mail_seen.message_id` 全局主键（`0011_mail.sql`），`mail_bridge.py:148-151` 查询无 list 过滤 → 跨列表误杀。
  - (k) fallback 指纹含 `utc_now()`（秒精度，`mail_bridge.py:145-147`）；`test_mail_bridge.py:116-122` 靠同秒执行才通过——flaky 且固化错误行为。
  - (l) `mail_bridge.py:169-190` 三条独立 execute（`execute_many` 未用）→ 崩溃时 seen 已提交、正文丢失且永久去重。
  - (m) `middleware.py:16` 全局 4MB 先于路由 10MB 生效；store 级测试绕过中间件掩盖此冲突。
  - 新问题：`digest_send_now` 用客户端任意 title/url 直接走用户 SMTP（`mail.py:185-189`）且无视 enabled；`delete_list` 缺 migrate+非事务；`mail_bridge_atoms` 表死 schema；Atom secret 在 URL path 泄入访问日志。
- Owner：IMPL-BE-2（Gate 3）。

### P0-07 — RAG 的语义检索并未真正建立 — `confirmed`

- 审计结论（BE-2 审计，7/7 证实）：
  - (a) `pyproject.toml:20-25` fastembed 在 optional extra `rag`；`Dockerfile:35` `uv sync --frozen --no-dev` 无 `--extra rag` → 生产镜像必无 fastembed，`enable()` 永远 `RagModelUnavailable`。
  - (b) **核心**：全库无任何 `INSERT INTO rag_vec`（`rag.py` 仅 CREATE :181 与 SELECT :390）；rebuild 只写 `rag_chunks.embedding`（:280-292）→ 语义腿永远 0 行，检索永远 lexical。
  - (c) `enableRag/rebuildRag/searchRag`（`client.ts:1650-1671`）零导入；唯一 UI 是只读 chip；`queries.ts:1450` 注释指向不存在的设置页。
  - (d) `unload_model`/`idle_expired` 无任何调用方 → 模型常驻到进程退出。
  - (e) 增删改不传播：library/entry 写路径无 rag 引用。
  - (f) rebuild：`DELETE` 后逐条 auto-commit（`execute_many` 未用）；title 硬编码 `""`（:288）→ title LIKE 腿永远不命中。
  - (g) `rag.py:238-240` 先 set enabled=1 再 warmup，失败无回滚；router 也不补。
  - 新问题：`_vec_search_sync` 每次查询重载 extension + 触私有 `_db._connect()`；`routers/rag.py:67` 死元组。
  - 测试盲区：`test_rag.py:158-172` 只断言 vec 表存在不断言有行；enable+rebuild 后 search 的测试不存在（存在就会抓住 (b)）；无任何 `/api/v1/rag/*` HTTP 级测试。
- Owner：IMPL-BE-2（Gate 5）。

### P0-08 — Agent 使用真实 provider 时第一轮就会失败 — `confirmed`

- 审计结论（BE-2 审计，8/8 证实 + 审批设计基本健全但有一处竞态）：
  - (a) `ai_provider.py:109-177` `chat_completion` 完整实现写在 Protocol 里（引用只有具体类才有的 `self._config/_client`）；`OpenAICompatibleProvider`（:195-295）只有 `summarize/complete` → `agent.py:87,201` 首轮 `AttributeError`，被 `routers/agent.py:93-98` 吞成"处理失败：…"文本。`test_agent.py:84-93` FakeProvider 恰好实现了该方法掩盖问题。
  - (b) SSE（`routers/agent.py:116-151`）是 1s 轮询 `store.messages_after` 重发整条持久化消息；UI 文档化轮询（`queries.ts:1390-1401`）。
  - (c) 无 cancel 路由；`agent_tasks` 只做 discard。
  - (d) `_history_for_provider`（`agent.py:218-238`）丢弃 assistant `toolCalls`、tool 结果包成 system 消息、approval 无分支 → 模型永远看不到 tool_call 关联；`test_agent.py:214-225` 把错误形状断言进测试。
  - (e) run 状态不持久化、重启不恢复 → 卡 processing；UI 无限轮询；`post_message` 无 per-thread 互斥；`agent_messages` 无 `UNIQUE(thread_id, seq)`（`0014_agent.sql`）→ seq 竞争损坏顺序。
  - (f) `deps.py:523-527` 三元条件在调用 `_get_obsidian_service` **之前**求值且 agent_loop 被 `_cached_on_app_state` 永久缓存 → 首个 agent 请求必然 obsidian=None，进程生命周期内 `list_notes` 永远空。
  - (g) 无 list-workspace 工具；`add_to_workspace` 默认 `read-later` 却不可枚举。
  - (h) 引用渲染为纯文本 join（`AgentWorkbenchPage.tsx:148-152`）。
  - 审批：绑定/一次性/TTL/hash 校验设计在（`agent_store.py:212-267`），但 (1) `take_approval` 读-改-写无 `AND status='pending'` 守卫、无事务 → 并发双执行；(2) `post_message` 不查 `has_pending_approval` → 审批挂起时可继续插入对话污染上下文；(3) `expire_stale()` 死代码；(4) hash 从消息日志重推而非 approvals 行（同源写，形同虚设）。
  - 新问题：`mail` 之外的 `Protocol` 结构化类型掩盖缺失方法（类型检查器抓不住）；SSE 60s 空闲即关。
- Owner：IMPL-BE-2（Gate 6）。

### P0-09 — Obsidian 在标准生产 Compose 下不可用 — `confirmed`

- 症状：无 vault 只读 bind mount 契约；用户填宿主机路径但容器内不可访问；只有手动重扫；正文静默截断；解析器粗糙；实时正文与旧索引元数据可不一致；相同内容两文件被误判 rename 复用同一 UUID；扫描写入无整体事务。
- 受影响文件：`obsidian.py`、`routers/obsidian.py`、`apps/web/src/pages/ObsidianPage.tsx`、`docker-compose.prod.yml`。
- 复现：prod compose 下配置宿主 vault 路径 → 扫描 0 文件。
- 数据风险：projection 与 vault 不一致；rename 误判造成引用漂移。
- 修复方案：只读 bind mount 到容器固定根目录（env 模板/UI/文档解释宿主↔容器路径）；traversal/symlink escape/设备/超大文件拒绝；增量扫描；事务化批次+checkpoint；rename 判定不用单一 content hash；显式截断状态；wikilink 解析真实 identity 或显式 unresolved；ItemRef 统一打开；远程浏览器不拿服务器绝对路径当本地 URI。
- 回归测试：100 代表性文件、同内容异路径、rename chain、symlink、中文文件名、frontmatter、wikilink 边界。
- Owner：主 Agent（Gate 4）。

### P0-10 — Tags/Graph、Favorites、Unified Search 的 UI 和语义未闭环 — `confirmed`

- 症状：后端 tag CRUD/attach 存在但前端基本没调用；Library favorite 无正常 UI 调用；workspace scope graph 混入全局 tag+全部 Obsidian；graph 截断数伪装总数；wikilink 生成虚假 synthetic node；tag 大小写敏感与“大小写不敏感去重”声明冲突；attach 先查上限后判幂等；不验证 ItemRef 存在；Unified Search/Favorites 的 Library 结果大量不可点、不可取消收藏；starred 搜索只过滤 RSS 却保留全部 Library 结果。
- 受影响文件：`tags.py`、`graph.py`、`favorites.py`、`search_library.py`、`routers/tags.py`、相关 Web 组件。
- 复现：UI 中尝试给内容打 tag → 无入口；workspace graph 出现非本 workspace 数据。
- 数据风险：tag 引用悬挂；graph 误导。
- 修复方案：完整 UI；幂等 API（先幂等后上限）；大小写一致约束（NORMALIZE 声明与实现一致）；ItemRef 存在性验证；graph scope 隔离+原始总数与截断数分离；全部结果可打开/可操作。
- 回归测试：30-tag 边界幂等、大小写重复、并发写入、scope 隔离。
- Owner：IMPL-FE + 主 Agent（Gate 1/7）。

### P0-11 — Translation 的 user activation 仍可能被异步链消耗 — `confirmed`

- 审计结论（UI 审计，file:line 证据已核）：
  - (a) **证实**：点击只切 state → effect → 120ms debounce → `LanguageDetector.create()`+`detect()` → `availability()` → `Translator.create()`（`ReaderTranslation.tsx:168-230`、`local-translator.ts:159-230`）；冷启动首次下载语言包时 activation 已被消耗，首次 NotAllowedError 是预期行为，只有重试按钮带新 activation（`ReaderTranslation.tsx:304-309`）。
  - (b) **证实**：检测真英语与探测失败都返回 `'en'`（`local-translator.ts:286-289`），UI 对真实英语也显示”（探测失败回退）”（`ReaderTranslation.tsx:358`）。
  - (c) **证实**：无同语言短路（`runLocalTranslation` 不比较 source/target；`createLocalTranslator` 无 guard）。
  - (d) **反证**：文章切换/取消防御完整（每 run 新 AbortController、cleanup abort、`key={translation-${entryRef}}` 重挂载、cancelled guard 全覆盖写路径）——旧译文不可能覆盖新文章。残余小问题：detect→create 之间不检查 abort（浪费下载）。
  - 新发现：`localTranslatorAvailable()` 导出但零调用——不支持的平台也渲染翻译控件，点开才知道不可用（`ReaderHeader.tsx:324-326`）。
- 修复方案：create() 移入手势内（预检提前缓存 availability/detect 结果）；真英语不标”回退”；同语言短路；不支持平台隐藏/禁用控件并给原因；每次重试新 activation。
- Owner：IMPL-FE（Gate 7）。

### P0-12 — 导航、文档和实际能力自相矛盾 — `confirmed`

- 审计结论（file:line 证据已核）：
  - Sidebar `PlannedItem`：”API 来源”（`Sidebar.tsx:550`）、”邮件简报”（`:551`）、”RAG 索引”（`:632`）标为 Phase 2 不可用（`Sidebar.tsx:76-101`）；折叠栏同样（`SidebarCollapsedRail.tsx:138,139,177`）；移动端复用同一 Sidebar。而 Settings 有完整可用的 `ApiSourcesSection`（`categories.tsx:342-347`）和 `MailSection`（`:348-353`）。
  - **RAG 三方矛盾**：nav 标不可用 + docs 称”已落地…显式启用”（`ROADMAP.md:23-24`）+ `queries.ts:1451` 注释称”操作入口在设置页”——但设置页无 RAG 分类；`enableRag/rebuildRag/searchRag`（`client.ts:1650-1671`）零调用；仅 AgentWorkbenchPage 只读状态 chip。
  - Settings”工作区”占位页自称”本页为占位，无可用功能”（`categories.tsx:403-408`），与 nav 已激活的 Agent 工作台/工作区页面矛盾，且同句承认剪藏/API 来源/邮件已可用——与 PlannedItem 冲突。
  - ROADMAP 漂移：read-later 跨设备同步列在”Next”但 M1 已实现服务端真源（`lib/read-later.ts:1-13`）；”Now: MVP 稳定化”与”Phase 2 已落地”并存。
  - a11y：`PlannedItem` 用不可聚焦 div + `aria-disabled`（屏幕阅读器通常不播报）；Graph 画布节点仅 tap 无键盘等价路径。
- 修复方案：导航状态来自真实能力（可用→入口；不可用→诚实禁用+指向 Settings）；补 RAG 设置入口；修正 Settings 占位文案；ROADMAP/README 与实现对齐；PlannedItem 语义修正。
- Owner：IMPL-FE + 主 Agent（Gate 7）。

### P0-13 — 搜索后台任务在 interval=0 时空转 — `confirmed`

- 症状：应用仍创建 search sync loop，`sleep(0)` 高 CPU 循环。
- 复现：interval=0 启动 → CPU 占用异常。
- 修复方案：禁用值不创建/不运行任务 + 回归测试。
- Owner：IMPL-BE-2 或主 Agent（Gate 0 顺手修）。

## 证据附录

（各 P0 的复现输出、失败测试、审计 file:line 证据，随 Gate 推进追加。）
