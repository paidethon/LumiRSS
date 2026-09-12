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

### 迁移编号预分配（防冲突，主 Agent 统一登记）

| 编号 | 内容 | Owner |
| --- | --- | --- |
| 0016_asset_origin | library_assets 增 url/原始元数据列（P0-04c） | IMPL-BE-1 |
| 0017_tag_name_nocase | tags 大小写不敏感唯一 + 既有变体合并（P0-10f） | 主 Agent |
| 0018_mail_list_scope | mail_seen 按 list 隔离 + 稳定指纹（P0-06j/k） | IMPL-BE-2 |
| 0019_api_source_lastgood | api_sources 持久化 last-known-good Atom + 状态（P0-05c/e） | IMPL-BE-2 |
| 0020_obsidian_scan_state | obsidian 扫描 checkpoint/截断状态（P0-09） | 主 Agent |

规则：新增迁移一律先在此登记编号；migrations 按文件名字典序发现。

### 共享文件所有权（实现期）

主 Agent 独占：`deps.py`、`main.py`、`itemref.py`/`sources.py`、`models.py` 的
workspace/tags/search/graph 段、`Dockerfile`、所有 compose/Caddy/env 样例、
`contracts/openapi.yaml` 与一切 generated 产物、迁移编号登记。
IMPL-BE-1/2 可对 `errors.py`/`models.py` 做**追加式 Edit**（只加自己域的段）。
其他共享文件变更以 diff 形式报给主 Agent 落地。


### BLOCKER-E1 — 生产直接核验（已解除只读部分；部署仍受发布门槛约束）

- 2026-09-13 用户提供 SSH 密钥（仅本会话使用，不入库不落盘他处）。
- **只读核验结果（2026-09-13）**：
  - 生产运行 `7d1191b7b603`（BFF 自报 commit 一致），BFF healthy；external-caddy 模式
    （宿主 Caddy → 127.0.0.1:18080），**basic 认证模式**（无 LUMIRSS_AUTH_MODE）。
  - **schema_version = 15**（迁移升级演练 v15→v20 与生产直接对应）。
  - Phase 2 数据量：library_items 1（clip）、agent_threads 1、workspaces 1（read-later）；
    api_sources/mail/obsidian/rag/tags 全部 0 —— 升级数据风险极低。
  - 备份：20260913-012436 存在（部署前备份）+ LATEST 指针；回滚快照 `.image-tag.previous`
    = `872035ab0ac5` ✓。
  - 资源：磁盘 24G 可用；**内存 1.6GB 总量 / ~770MB 可用** —— 生产部署必须沿用低内存
    预算（RAG 显式启用+空闲卸载是硬要求）。
  - `.env.prod` 无 OBSIDIAN/ATOM_BASE_URL 变量（缺省值可用）；`LUMIRSS_INTERNAL_TOKEN`
    已设置 → bearer-defer 中间件修复对该部署直接生效。
- 部署条件仍按指令 §10：全 P0 关闭 + required checks 绿 + Compose E2E 绿 + 演练通过后才执行；
  执行方式 `./lumirss update`（GHCR 私有 → 服务器本地构建）。
- **部署配置注意事项**：宿主 Caddy basic auth 会拦 `/api/mail/ingest/*` 的机器投递——
  生产启用邮件桥前需在宿主 Caddy 豁免该路径（或中继带上 basic 凭据）；当前生产无邮件
  列表，非本次部署阻塞。

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
- FE wave2 ✓：稍后读视图改走服务端时间线 `GET /workspaces/read-later/timeline`（useInfiniteQuery cursor 分页 + 无限滚动哨兵）；删除 view=all 本地过滤（`toApiView` 退役、useEntries 对 read-later 禁用）、删除 localStorage 双写与 zustand store（`store/read-later.ts` 删除、once-only syncedRef 对账删除）；toggle 走 useReadLaterMemberMutation（乐观移除+失败回滚+共享 cache 失败告警+`['workspace','read-later']` 前缀失效），Clock 激活态来自服务端 refs 清单；悬挂成员 stale 行显式渲染+移除出口（tests: read-later 9 + timeline-gate2 9 + scroll-mark-unread 5 passed）。locally_verified。

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
- 实现: 服务端管线落地 — `article_extract.py`（readability 式正文/标题/署名提取，纯 stdlib）+ `article_sanitize.py`（allow-list 清洗：去 script/iframe/object/embed、on* 属性、javascript:/data: URL、CSS expression，深度/体积封顶）+ `ssrf_transport.py`（resolve→全地址校验→按钉住 IP 直拨，Host/SNI 保持原身份，杀 DNS-rebinding TOCTOU）+ `clip_fetch.py`（每链路 30s 总预算、validate_hop 捕 OSError、返回 finalUrl）+ `db_tx.py` + `library_clips.py` 事务化写入（identity+clip+search 投影单事务，IntegrityError 回滚无孤儿）。POST /clips/fetch 返回服务端提取+清洗后的文章（title/byline/contentHtml/contentText/finalUrl）；POST /clips 不再信任任何客户端 HTML（deprecated 字段接受但忽略，服务端按 finalUrl 重取重导出）。测试: `test_clip_pipeline.py`（恶意 HTML 矩阵）+ `test_ssrf_transport.py`（钉住拨号/私有拒绝先于拨号/真实本地源 Host+SNI 端到端）+ `test_clip_fetch.py`（重定向 finalUrl/链路预算/MIME/全管线）+ `test_library_clips.py`，6 文件合计 59 passed。

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
- 实现: (a) Dockerfile 安装 diff 已提交主 Agent（pin v2.10.1 + sha256）。(b) argv 实测 v2.10.1 `--help` 修正为 `<url> -o <file> -t 60 -I -j`（x86_64 sha256 `663ca914…05df`，aarch64 `7f8cac62…9997`），去掉 `-C 1` cookie 误用与 `-e`（网络错误保持 fatal=诚实）；真实二进制 e2e：页面与全部子资源以 absolute-URI 经 HTTP_PROXY 到达代理，失败 exit≠0 不写产物。(h) 子资源 SSRF 闭环：新模块 `ssrf_proxy.py` 进程内正向代理，每请求 resolve→ensure_public_address→按钉住 IP 直拨（http origin-form 转发；https CONNECT 校验后盲隧道），不可解析/非公网/非 http(s) 一律 403 fail-closed（实测 169.254.169.254 → 403 → monolith exit 1 无产物）；runner 用最小子进程 env（PATH+代理变量）接线。(c) migration `0016_asset_origin.sql` 增 `url`（旧行回填 ''），列表端点返回真实 url。(d) dedupe 语义修正 True=本次保存复用已有字节，列表返回真实值（同秒保存按 (created_at,uuid) 规范序推导）。(e) 配额按每 sha256 计费一次。(f) 删除=资产行+身份行单事务，末引用提交后 unlink。(g) 保存先落盘后单事务、失败补偿删文件，`reconcile()` 清扫孤儿文件/死行。测试: `test_library_snapshots.py` + `test_ssrf_proxy.py` 等 8 文件合计 82 passed。

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
- FE wave1 ✓：workspace 重命名/删除 UI（PATCH/DELETE + 双重确认，保留工作区不给入口，queries 失效 ['workspaces']/['workspace']）；条目标签 attach/detach（EntryActionButtons 标签 Popover：useItemTags 勾选真值 + useTags 全量 ∪ suggested + 新建；assignTag/unassignTag 首批消费者）；标签管理收在图谱页标签列表行内菜单（重命名/删除，最小可发现面）；库收藏切换（UnifiedContentCard 库类 kind + FavoritesPage LibraryRow 取消收藏；乐观移除+回滚+诚实错误，RSS star 不动）（tests: p0-10-closures 9 + library-ui 11 passed）。locally_verified。
- FE wave2 ✓：「一切皆可打开」——UnifiedContentCard 默认按 kind 路由打开（lib/open-item.ts：rss→Reader、bookmark rss 型→Reader/外链、clip→剪藏 section、snapshot→服务端沙箱页新标签、obsidian_note→Obsidian section；WorkspacesPage 不传 onOpen 也生效）；FavoritesPage/SearchPage 库行从惰性文本改为 resolve→路由打开（stale 行禁用+「已失效」注明）；图谱摘要行截断时如实分列「真实总数 vs 仅返回数」（totalNodes/returnedNodes），节点详情卡加「打开」，unresolved wikilink 显式未解析样式；Agent 引用改经 POST /api/v1/resolve 批量解析为可点按钮、失效为纯文本（tests: library-ui 15 + p0-10-closures 9 + agent-graph-ui 8 passed）。locally_verified。

### P0-11 — Translation 的 user activation 仍可能被异步链消耗 — `confirmed`

- 审计结论（UI 审计，file:line 证据已核）：
  - (a) **证实**：点击只切 state → effect → 120ms debounce → `LanguageDetector.create()`+`detect()` → `availability()` → `Translator.create()`（`ReaderTranslation.tsx:168-230`、`local-translator.ts:159-230`）；冷启动首次下载语言包时 activation 已被消耗，首次 NotAllowedError 是预期行为，只有重试按钮带新 activation（`ReaderTranslation.tsx:304-309`）。
  - (b) **证实**：检测真英语与探测失败都返回 `'en'`（`local-translator.ts:286-289`），UI 对真实英语也显示”（探测失败回退）”（`ReaderTranslation.tsx:358`）。
  - (c) **证实**：无同语言短路（`runLocalTranslation` 不比较 source/target；`createLocalTranslator` 无 guard）。
  - (d) **反证**：文章切换/取消防御完整（每 run 新 AbortController、cleanup abort、`key={translation-${entryRef}}` 重挂载、cancelled guard 全覆盖写路径）——旧译文不可能覆盖新文章。残余小问题：detect→create 之间不检查 abort（浪费下载）。
  - 新发现：`localTranslatorAvailable()` 导出但零调用——不支持的平台也渲染翻译控件，点开才知道不可用（`ReaderHeader.tsx:324-326`）。
- 修复方案：create() 移入手势内（预检提前缓存 availability/detect 结果）；真英语不标”回退”；同语言短路；不支持平台隐藏/禁用控件并给原因；每次重试新 activation。
- Owner：IMPL-FE（Gate 7）。
- FE wave1 ✓：点击→Reader 注册回调手势内直接编排（effect+120ms 降为二等路径）；detectArticleLanguage 判别 {lang,via}、真英语不再标回退；同语言短路零 translate()；availability 模块级缓存 + 探测 ref 缓存；detect→create 跨 await abort 检查；不支持平台控件禁用+原因（localTranslatorAvailable 首批消费者）；真实 activation 验证留给 headed-Chrome 矩阵（tests: local-translator 16 + browser-engine 5 + gesture 7 passed）。locally_verified（jsdom 编排契约）。

### P0-12 — 导航、文档和实际能力自相矛盾 — `confirmed`

- 审计结论（file:line 证据已核）：
  - Sidebar `PlannedItem`：”API 来源”（`Sidebar.tsx:550`）、”邮件简报”（`:551`）、”RAG 索引”（`:632`）标为 Phase 2 不可用（`Sidebar.tsx:76-101`）；折叠栏同样（`SidebarCollapsedRail.tsx:138,139,177`）；移动端复用同一 Sidebar。而 Settings 有完整可用的 `ApiSourcesSection`（`categories.tsx:342-347`）和 `MailSection`（`:348-353`）。
  - **RAG 三方矛盾**：nav 标不可用 + docs 称”已落地…显式启用”（`ROADMAP.md:23-24`）+ `queries.ts:1451` 注释称”操作入口在设置页”——但设置页无 RAG 分类；`enableRag/rebuildRag/searchRag`（`client.ts:1650-1671`）零调用；仅 AgentWorkbenchPage 只读状态 chip。
  - Settings”工作区”占位页自称”本页为占位，无可用功能”（`categories.tsx:403-408`），与 nav 已激活的 Agent 工作台/工作区页面矛盾，且同句承认剪藏/API 来源/邮件已可用——与 PlannedItem 冲突。
  - ROADMAP 漂移：read-later 跨设备同步列在”Next”但 M1 已实现服务端真源（`lib/read-later.ts:1-13`）；”Now: MVP 稳定化”与”Phase 2 已落地”并存。
  - a11y：`PlannedItem` 用不可聚焦 div + `aria-disabled`（屏幕阅读器通常不播报）；Graph 画布节点仅 tap 无键盘等价路径。
- 修复方案：导航状态来自真实能力（可用→入口；不可用→诚实禁用+指向 Settings）；补 RAG 设置入口；修正 Settings 占位文案；ROADMAP/README 与实现对齐；PlannedItem 语义修正。
- Owner：IMPL-FE + 主 Agent（Gate 7）。
- FE wave1 ✓：API 来源/邮件简报 nav → 真实入口（settings-bridge 新增 requestOpenSettings 深链，桌面 Modal 与移动全屏页共用；未知分类降级 general）；RAG 索引选择「诚实禁用 + 指向 Agent 工作台」（不称规划中，badge 见工作台——独立管理 UI wave 2）；Settings 工作区卡改为「已上线」并指向真实入口；PlannedItem/RailItem 改真 disabled button + 说明（a11y）（tests: p0-12-navigation 5 + gate-c 10 + agent-graph-ui 7 passed）。locally_verified。
- FE wave2 ✓：RAG「独立管理 UI」兑现——设置 → AI 新增「语义检索（RAG）」分类（RagSettingsSection：状态 enabled/chunks/model/lastRebuildAt、启用 POST /rag/enable（fastembed 未装禁用+说明）、重建 POST /rag/rebuild（busy+完成报告+RagRebuildBusy 原样透出）、lastError 展示），enableRag/rebuildRag 首批真实消费者、queries.ts:1450 注释成真（tests: rag-settings 5 passed）。locally_verified。

### P0-13 — 搜索后台任务在 interval=0 时空转 — `confirmed`

- 症状：应用仍创建 search sync loop，`sleep(0)` 高 CPU 循环。
- 复现：interval=0 启动 → CPU 占用异常。
- 修复方案：禁用值不创建/不运行任务 + 回归测试。
- Owner：IMPL-BE-2 或主 Agent（Gate 0 顺手修）。

## 证据附录

### 修复进度（按 Gate）

- **迁移升级演练** ✓：以 7d1191b 的迁移集构建真实 v15 库（种入书签数据）→ 当前代码升级 →
  0016–0020 全部应用，schema_version 20，数据存活，`ix_tags_name_nocase` 就位。UPGRADE OK。
- **生产镜像 monolith** ✓：`docker build` 成功（arch 探测改 uname -m 以兼容 legacy builder，
  `28021fd`）；镜像内 `monolith --version` = 2.10.1，非 root 可执行。
- **P0-13** ✓ `6600c33`：interval=0 不再创建任务；负值被 config 拒绝；3 个回归测试。locally_verified。
- **Gate 1 后端（主 Agent）** ✓ `83e5066`：
  - P0-02：resolve_library 按 kind 分派（bookmark/clip/snapshot/obsidian_note）+ 打开 payload + 并发 batch resolve；20 个回归测试（test_gate1_foundations.py）。locally_verified。
  - P0-10 后端：attach 幂等优先、NOCASE（migration 0017 合并变体）、ItemRef 存在性验证（workspace/tag/favorite）、graph scope 全边隔离 + totalNodes 真实总数 + wikilink 解析真实 note/显式 unresolved、starred 过滤作用于 library 腿、tag→items 服务端列表端点。**额外发现并修复**：DELETE /tags/assign 被 /{tag_id} 路由捕获的声明顺序 bug（detach 自上线即不可用）。
  - P0-01 后端：GET /workspaces/read-later/timeline 服务端时间线（keyset 分页、投影优先+adapter 回退、悬挂成员 stale 可见）。
- **Gate 4（主 Agent）** ✓ 已提交 `49ce2b8`：env 固定 vault 根 + 只读 bind mount overlay（docker-compose.obsidian.yml + ./lumirss 自动接线 + env 样例）；rename 消歧（唯一删除者+唯一新增者）；单事务扫描批次；索引快照一致渲染；显式截断（migration 0020 + truncatedNotes + NoteView.truncated）；LUMIRSS_OBSIDIAN_SCAN_INTERVAL 轮询；缺失 note 404；服务启动即构建（同时封死 P0-08f 的 deps 竞争后端半边）；10 个回归测试（test_obsidian_gate4.py）。备份含资产字节（library-assets/ 组件 + restore 回填）。
- **BE-1（Gate 2 剪藏/快照/SSRF）** ✓ 已提交 `7d7a41a`：服务端提取+清洗管线、PinnedAddressTransport（TOCTOU 关闭）、SsrfFilteringProxy（真实 monolith 验证，元数据 IP 403 无产物）、monolith 2.10.1 checksum 入镜像、argv 修正、dedupe 语义修正、配额按唯一字节、事务化+补偿+reconcile；范围内 82 passed。
- **BE-2（Gate 3 API源/邮件）** ✓ 已提交 `2462ffd`（报告已交付；范围内 52 passed + 3 xfail；接线后本机复跑 83 passed + 2 xfail + 1 xpass）：
  - P0-05：共享 RFC4287 渲染器 atom_render.py；feed updated 内容派生+单调；稳定 ETag+可靠 304（修 flaky 同秒断言）；last-known-good 持久化（migration 0019）+ `X-Lumi-Stale` 降级；退订失败阻止删除（409 unsubscribe_failed）；双 base URL（默认 `http://bff:8000`）；fetch_json 流式 2MB 上限（修 OOM DoS）。
  - P0-06：per-list 去重（migration 0018）+ 稳定内容指纹；ingest 单事务；webhook bearer 通路（middleware 三处 defer + 10MB 路径限额，主 Agent 已落地）；scheduler/IMAP 任务工厂入 lifespan（主 Agent 已落地）；send-now 服务端取材（422 no_digest_items）；FreshRSS 自动订阅（诚实 subscribeFailed）；IMAP await 修复+配置/测试/轮询端点；Atom 合规。xfail 已移除、凭据字面量已清。
- **BE-3（Gate 5+6 RAG/Agent）** ✓ 已提交 `341d598`（范围内 92 passed + 1 skipped；真实模型 smoke 通过）：
  - P0-07：rebuild 真写 `rag_vec`（核心缺陷）+ 单事务索引写入；**新发现并修复** fastembed `model=` kwarg 静默吞掉（始终加载默认英文模型）→ model_name + identity 校验 + 维度探测 fail-closed；enable 先 warmup 后持久化；idle-unload 生命周期任务；mark_stale/index_refs 增量钩子（已接线 bookmark/clip/snapshot 删除路由）；title 持久化；Dockerfile `--extra rag`（主 Agent 落地）。
  - P0-08：chat_completion 下沉到具体类（首轮 AttributeError 关闭）；真 SSE 流式（增量持久化+队列广播）；server-side cancel + 重启 sweep（不卡 processing）；per-thread 串行 + pending approval 409；审批原子化（rowcount 条件 UPDATE + 行内 args 校验）；history 符合 OpenAI tool 协议（错误形状测试修正）；list_workspace_items 工具；obsidian 工具初始化竞争回归测试；citationDetails（ResolvedItem 契约）供 FE 渲染可点引用。
- **FE 波 2（最终 Web 波）**：代码完成（详见下方 ✓ 行与 P0-01/P0-10/P0-12 行；未提交，待主 Agent gate 验收）。
- **FE 波 2（最终 Web 波）** ✓：全部工作项落地——P0-01 客户端（见 P0-01 行）、P0-02 打开路由+统一 resolve（POST /api/v1/resolve client/queries；payload per-kind 契约 lib/open-item.ts）、P0-03 客户端（ClipsPage 改服务端管线：fetch 展示服务端文章确认 → 保存只提交 {url, finalUrl}；`clip-extract.ts` 删除、defuddle/@mozilla/readability 依赖移除；渲染前 DOMPurify 终界不变；tests: clips-ui 9）、P0-05 客户端（ApiSourcesSection 409 unsubscribe_failed 重试提示透出，沿用现有错误行）、P0-06 客户端（MailSection 收信地址→「HTTP 转发入口（webhook）」、绝对 ingest URL、subscribeFailed+atomPath 警告、no_digest_items 422 原样透出；tests: g6-ui 14）、P0-07 客户端（见 P0-12 行）、P0-08h 客户端（citations 可点，见 P0-10 行）、P0-09 客户端（ObsidianPage envRootConfigured 挂载模式不问宿主路径+宿主→容器只读挂载说明+env 模式不渲染 obsidian:// 深链；NoteView.truncated 显式「已截断」提示；tests: g6-ui）、契约修复（MailBridgeListCreatedV2/ClipFetchArticleResult/DigestSendNowRequest.messageId/GraphResponse.returnedNodes 对齐 regenerated schema；tests: client.test 27）。22 文件 209 tests passed；tsc -b 干净；oxlint 0 errors（warnings 与基线持平）。locally_verified（jsdom；真实网络/compose 冒烟留给主 Agent gate）。

（各 P0 的复现输出、失败测试、审计 file:line 证据，随 Gate 推进追加。）

### Gate 8 — production-like Compose E2E（2026-09-13）

- 栈：生产 Dockerfile 构建的 bff 镜像（monolith 2.10.1 checksum 校验 + `--extra rag`）、
  web/Caddy（session 模式）、FreshRSS 1.29.1、RSSHub、本地 SMTP 接收器、受控 fixtures、
  脚本化 OpenAI 兼容服务器、只读 vault。
- **run-smoke 15/15 PASS**：session 登录 / read-later 服务端时间线（FreshRSS 真实抓取后的
  条目）/ 混合工作区 / 剪藏服务端提取+恶意 HTML 清理 / 生产镜像内真实 monolith 快照 /
  /feeds 经 Caddy / FreshRSS 容器抓取生成的 Atom / 稳定 ETag+可靠 304 / webhook bearer
  通路 / 空摘要拒绝 / Obsidian 挂载+同内容双身份 / RAG 诚实状态 / Agent 线程 / tag 幂等 /
  backup 作业。
- **新特性（E2E 发现的真实需求）**：`LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS` 运维私网主机名
  允许列表（默认空=行为不变；仍走 解析→验证→固定 IP 拨号），自托管内网源（内网 RSSHub）
  所需。
- **最终全量验证**：BFF 933 passed（基线 778）+ ruff clean；Web 710 passed（基线 669）+
  lint 0 errors + build/bundle guard OK + tsc clean；OpenAPI/settings drift 干净。
- **迁移升级演练**：v15（= 生产现状）→ v20 全部应用、数据存活、NOCASE 索引就位。
- **备份/恢复**：资产字节随 full backup 归档（library-assets/ 组件）+ restore 原地回填 +
  往返测试通过。
- **回滚方案**：应用回滚 = 上一镜像 tag + 向前兼容数据库（生产 `.image-tag.previous`
  机制已在位）；schema 仅前向累加，v15 旧代码可运行于 v20 库（升级演练反向兼容证明）。
- 迭代中修复的部署真相：FreshRSS CLI 配置后必须 `access-permissions`/chown（否则 greader
  登录 "configuration cannot be found"）——已固化进 run-smoke.sh 的 init。
