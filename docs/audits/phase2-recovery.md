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

- 审计结论（BE-3 审计，4/4 证实）：
  - (a) `lib/read-later.ts:39-41` `toApiView()` 把 read-later 映射成 `all`；`navigation.ts:42-47` 同样；`EntryList.tsx:58-65` 对已加载页本地过滤——未翻到的页不可见。
  - (b) `routers/entries.py:43` view 只有 all/unread/starred；服务端唯一事实是保留工作区 `read-later`（`workspaces.py:19`，migration 0008 种子）但其端点返回 refs/ViewModel，不是 entries 查询。
  - (c) `read-later.ts:70-71,80` `syncedRef` 只在首次成功 fetch 对账一次；toggle 直接调 client 绕过 mutation → 无 invalidateQueries → 他端变更只在整页重挂载后可见。
  - (d) `read-later.ts:58-60` `.catch` 吞掉失败注释"本地缓存保留"→ 乐观状态不回滚；remove 400 也静默。
  - 新问题：`EntryList.tsx:186-196` read-later 视图的 filteredCount 把被隐藏项算进"规则过滤"；`read-later.ts:113-117` hydration 用 `Date.now()` 盖掉真实 addedAt 顺序。
  - 测试：`read-later.test.tsx:150,193` 把客户端过滤/双写设计固化进断言（修时要改）。
- 修复方案（Gate 1）：服务端 read-later 时间线（entries 查询按保留工作区成员过滤，可分页可排序：`view=read-later` 由 BFF 直查 FreshRSS starred/read-later 成员交集或直接列 workspace members 的 rss refs 解析）；客户端删除本地过滤、toggle 走 mutation+invalidate、失败回滚+错误 toast；同步去掉 once-guard。
- Owner：主 Agent（Gate 1，后端）+ IMPL-FE（客户端）。

### P0-02 — ItemRef / Source Registry 只真正解析 bookmark — `confirmed`

- 审计结论（BE-3 审计，证实；措辞修正：ref 无 per-kind 编码，kind 在 `library_items.kind`）：
  - 唯二 resolver：`rss`（`deps.py:583-621`）、`library`（`:623-641`）；后者走 `LibraryStore.get_library_item`，非 bookmark 一律 None（`library.py:235-245`）→ `sources.py:88-97` 变 `kind=unknown/title=内容不存在/stale=True`。
  - clip（`library_clips.py:98`）、snapshot（`library_assets.py:98,127`）、obsidian_note（`obsidian.py:324`）都写 `library_items`——全部解析失败。
  - resolve 的调用方只有 `routers/workspaces.py:186,202`（workspace contents + 批量 resolve）；tags/search/graph/agent 直接存/渲染原始 refs；agent 的 `get_library_item` 工具（`agent_tools.py:75`）同样 bookmark-only。
  - 测试盲区：`test_workspaces.py:161-189` 只测 rss+bookmark；无任何测试解析过 clip/snapshot/obsidian ref。
- 修复方案（Gate 1 基础）：`resolve_library` 按 kind 分派到 owning store 的视图构造（bookmark/clip/snapshot/obsidian_note；api_item/newsletter_item 按 ADR 0004 说明其可解析性），附统一 `openTarget`（reader/外部 URL/沙箱快照页/obsidian note 页）；existence validation 供 tags/favorites/agent 复用；batch resolve 并发化（审计新问题 #4：串行 N 次 FreshRSS 往返）。
- Owner：主 Agent（Gate 1 基础）。

### P0-03 — Clipping 信任浏览器提交的 HTML — `confirmed`

- 审计结论（BE-1 审计，3/3 证实）：
  - 服务端抓原始 HTML 返回浏览器（`routers/clips.py:48-52`）→ 浏览器 DOMPurify 提取（`clip-extract.ts:61-126`）→ 客户端 `contentHtml` 原样 POST 回（`client.ts:1082-1091`）→ 服务端 `_validate_html` 只查非空+2MB（`library_clips.py:230-235`）原文入库（`:87,108`）。docstring 自认信任边界在客户端（`library_clips.py:4-9`）。
  - 多步写入无事务：`library_clips.py:96-118` 三条独立 execute（`storage.py` 每条自动提交；`execute_many` 未用）→ 孤儿 `library_items`/不可搜索 clip；delete 同样（:141-142）。
  - SSRF 防线盘点（已有，较强）：http/https+端口+长度（`feed_preview.py:124-135`）；每跳 getaddrinfo 全地址检查含 IPv4/IPv6 私网/环回/链路本地/CGNAT/NAT64（`clip_fetch.py:63-85`、`feed_preview.py:138-155`）；手动重定向 ≤5 跳；MIME html/xml；5MB 流式上限（压缩炸弹有界）；20s/请求；`trust_env=False`。
  - **未缓解**：DNS rebinding TOCTOU（校验后 httpx 二次解析，未钉住地址）；每请求 20s 非每链路（5 跳可占 worker ~2 分钟）；`validate_hop` 只捕 `socket.gaierror`（OSError 变 500）。
  - 新问题：`fetch_for_clip` 返回原始 URL 而客户端存原始 URL（重定向后 dedupe/展示错位，`routers/clips.py:52`）；`fetchedAt` 客户端任意字符串未验证。
- 修复方案：服务端提取+sanitize 管线（readability 类算法在 BFF 内实现），浏览器只提交 URL；钉住已校验地址（自研 resolver 或连接前校验）；每链路总时限；事务化写入。
- Owner：IMPL-BE-1（Gate 2）。

### P0-04 — Snapshot 在生产镜像中不可用且命令错误 — `confirmed`

- 审计结论（BE-1 审计，8/8 证实）：
  - (a) `Dockerfile:16-64` 无任何 monolith 安装/复制；compose/deploy 脚本也无 → `shutil.which` None → 503 `monolith_unavailable`，生产即死功能。
  - (b) `snapshots.py:64-75` argv：`binary, url, str(out_path), "-t","60","-I","-C","1"`——out_path 作第二个位置参数（正确是 `-o <file>`）；`-C 1` 是 cookie 文件（`_SNAPSHOT_PROMPT` 变量名坐实误读）。
  - (c) `library_assets` 无 url 列（`0009:21-30`）；列表端点硬编码 `url=""`（`routers/snapshots.py:64`）→ UI 原文 URL 恒空。
  - (d) dedupe 布尔反转：`library_assets.py:115` 已去重返回 False、`:136` 新写入返回 True → "已去重"徽章显示在全新内容上；`test_library_snapshots.py:42,56` 把反转语义断言进测试。
  - (e) 配额按行数计费：`_bytes_on_disk`=SUM(行字节数)（`:185-189`）→ 去重行携带全额字节数重复计费；UI 显示虚高值。
  - (f) `delete_asset` 只删 assets 行（`:165-183`）→ `library_items` 永久孤儿。
  - (g) 文件先落盘后两条独立 insert（`:119-133`）；删除先删行后删文件——两方向都不原子。
  - (h) monolith 子资源抓取无任何约束（docstring 自认 fail-closed 只在顶层 URL）→ 公网页面可引用内网资源嵌入产物，经同源 `/api/v1/library/assets/{uuid}/page.html` 提供（服务端外泄通道）。
  - 新问题：列表响应永远 `deduplicated=False`（模型默认值，路由漏字段）。
- 修复方案：固定版本+checksum 安装 monolith 进生产镜像；`monolith <url> -o <file> -I -t 60` 按真实 CLI；持久化原始 URL+创建时间+物理大小（forward migration 或复用列）；去重语义修正+测试反转断言修正；配额按物理唯一字节；引用计数删除+事务；**子资源 SSRF：monolith 无内建代理/白名单能力 → 默认禁用远程子资源（`-i` 本地图片？需按固定版本 `--help` 核实）或网络级隔离；无法安全约束则如实禁用远程 snapshot**。
- Owner：IMPL-BE-1（Gate 2）。

### P0-05 — API Source 的 feed 地址、Atom 与缓存逻辑不成立 — `confirmed`

- 审计结论（BE-1 审计，6/6 证实）：
  - (a) `routers/api_sources.py:104` 默认 base `http://127.0.0.1:8000`（FreshRSS 容器里指向自身）；`LUMIRSS_ATOM_BASE_URL` 默认空且**不在 `.env.prod.example`**、prod compose 不设置。
  - (b) `Caddyfile.auth:19-23`/`noauth:17-21` 只代理 `/api/*`，`/feeds/*` 落 SPA fallback 返回 index.html。设计意图是 FreshRSS 走 docker 网内直连 BFF（故 Caddy 不代理是刻意的）——但 (a) 使网内地址也不可用；且 config 注释示例 `http://lumirss-bff:8000` 与 compose 服务名 `bff` 不一致（容器名恰好可解析）。
  - (c) `api_sources.py:248` feed `updated`=每请求 `utc_now()`；ETag=body sha256 → 每秒变化；持久化 `etag` 列是只写死代码（`api_source_store.py:119-123`）。`test_api_sources.py:133-136` 的 304 断言靠两次 GET 落同一秒才过——flaky 且掩盖此缺陷。
  - (d) entry 无 `<updated>`（RFC 4287 §4.2.2 必填）、无 author；`rel=self` 是相对 URI（`self_base=""`）。
  - (e) 上游失败返回 502 `<error>` stub，Atom 正文从不持久化 → 无 last-known-good 可服务。
  - (f) `routers/api_sources.py:141-149` 删除时丢弃 `_unsubscribe_best_effort` 错误 → 死订阅继续轮询已 404 的 URL。
- 修复方案：明确双 base URL 契约（容器内 `LUMIRSS_ATOM_BASE_URL` 必填进 env 样例+compose；浏览器/Caddy 路径按需）；`updated` 取内容/last-success 状态（持久化+单调）；entry 补 updated/author；ETag 稳定+304 可靠（修 flaky 测试）；持久化 last-known-good Atom 服务 stale+`X-Lumi-Stale`/lastStatus 暴露；退订失败阻止删除并报错；RFC 4287 全结构验证测试。
- Owner：IMPL-BE-2（Gate 3）。

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

- 审计结论（BE-3 审计，8/8 证实）：
  - (a) prod compose bff 卷只有 lumi-data + freshrss-data:ro（`docker-compose.prod.yml:69-71`）；config/env 均无 vault 变量。
  - (b) UI 让用户填"服务器本机绝对路径"（`ObsidianPage.tsx:90,102`），BFF 在容器内 `resolve(strict=True)`（`obsidian.py:70-82`）→ 503 vault_unreachable；即使手工挂载，存储的容器路径又与 `obsidian://` 深链的宿主路径分叉。
  - (c) 唯一触发是手动 `POST /obsidian/rescan`；无 watcher/polling。
  - (d) 静默截断：body 20000（`:186`）、search body 4000、title 500/tags 30/wikilinks 100；ScanReport 不报告。
  - (e) 解析器粗糙：naive `split("[[")`（代码块内 wikilink/`![[embed]]` 误捕）；行内 tag=任意 `#` 开头 token；frontmatter 失败整篇进 skipped。
  - (f) `get_note` 渲染实时文件 HTML 但 tags/wikilinks/bodyText 取自索引行（`:398-428`）→ 重扫前不一致。
  - (g) `hash_to_uuid`（`:260-263`）+ adopt 逻辑（`:274-284`）：同内容第二文件偷走 UUID、原路径行被当 removed 删除——两个 vault 文件共享一个 identity。
  - (h) 每 note 3 条独立 execute + 删除循环无事务（`_insert_note:321-347`）→ 半更新 projection（library_items 行无子行 → 永久"内容不存在"）。
  - 新问题：不存在的 note 报 503 而非 404（`routers/obsidian.py:69-76`）；parse_note 同步读文件阻塞事件循环（`:268`）；favorites 里 search_library 缺失的 ref 永不清理。
- 修复方案（Gate 4，主 Agent）：`OBSIDIAN_VAULT_DIR` 容器固定根 + prod compose 只读 bind mount + env 模板/UI/文档解释宿主↔容器路径；traversal/symlink escape/设备/超大拒绝；增量扫描（mtime+size checkpoint）；批次事务；rename 判定（path+content hash 组合，不做单一 hash adopt）；显式截断状态字段；wikilink 解析真实 identity 或显式 unresolved；`obsidian://` 深链只用宿主配置路径（不泄漏容器内路径）。
- Owner：主 Agent（Gate 4）。

### P0-10 — Tags/Graph、Favorites、Unified Search 的 UI 和语义未闭环 — `confirmed`

- 审计结论（BE-3+UI 审计，10/10 证实）：
  - (a) 后端 CRUD/attach 全在（`routers/tags.py:25-125`）；web 的 assign/unassign/rename/deleteTag 零 UI 调用者；唯一消费者是 GraphPage 只读图例。
  - (b) `addLibraryFavorite/removeLibraryFavorite`（`client.ts:1398-1412`）零调用；FavoritesPage 只读、无取消收藏。
  - (c) graph workspace scope 只过滤 workspace 边（`graph.py:69-78`）；tag 边（:58-66）与全部 Obsidian wikilink（:87-89）永远全局。
  - (d) `_truncate` 截断后 `totalNodes=len(截断集)`（`graph.py:34`）——真总数丢失；web 恰好没显示 totalNodes（显示 nodes.length+truncated 提示）。
  - (e) wikilink 目标 = `wiki:<relPath>:<target>` 合成节点（:97-101），从不解析到真实 note。
  - (f) docstring 声称 case-insensitive dedupe，`normalize_tag_name`（`tags.py:43-51`）无 casefold；`0015_tags.sql:5-8` UNIQUE BINARY 大小写敏感。rename 的 dupe 检查同样精确匹配（可造出大小写变体重复）。
  - (g) `attach` 先查 30 上限（:123-128）后判幂等（:129-140）→ 满上限时重复 attach 报错而非幂等返回。
  - (h) attach 只验证格式不验证目标存在（:105）。
  - (i) SearchPage LibraryGroup 行是惰性 `<li>`（`SearchPage.tsx:100-121`）；FavoritesPage LibraryRow 只有外链——obsidian/clip `url=None` 永远不可打开；workspace contents 又因 P0-02 变”内容不存在”。
  - (j) `routers/search.py:79-89` starred/unread 等过滤只作用 RSS 腿，library 腿无过滤透传。
  - 新问题：search library 腿分页重复行（每页重跑无游标查询+flatMap）；favorites `rss:` ref 可收藏但库腿永不显示且不清理；AI tag suggestion 用裸 ref 做 prompt 且 `existing` 计算后丢弃；`test_tags_graph.py:131` 死代码；FavoritesPage 重复 DateGroup 接口声明。
- 修复方案（Gate 1 后端 + Gate 7 UI）：attach 幂等优先+existence validation（走统一 resolver）；大小写策略落地（决定：NFC+casefold 唯一性，forward-compatible——同名不同 case 归并为已有 tag，迁移脚本合并既有 case 变体）；graph scope 作用于全部边类型+返回 raw total 与返回数两个数字；wikilink 解析真实 note/显式 unresolved；UI 全闭环（见 IMPL-FE）。
- Owner：主 Agent（后端语义）+ IMPL-FE（UI）。

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
