# 上游对照（Upstreams）

> FreshRSS 与 RSSHub 的能力覆盖矩阵与委托边界。LumiRSS 是组合成熟引擎
> 的产品层：本页逐域回答"这个能力谁拥有、Lumi 是否有通道、证据在哪"。
> 架构不变量（FreshRSS 拥有 RSS 域、浏览器只与 BFF 通信、RSSHub 只是
> feed 生成器）见 [architecture](/architecture)。全量功能对照的离线
> 单页见[上游功能对照矩阵](/reference/upstream-feature-matrix.html)
> （FreshRSS/RSSHub 50 能力族 + 131 路由目录）。

## FreshRSS 能力覆盖（P09）

> 行 = FreshRSS 能力域；每行给出 FreshRSS 侧支持情况（含官方文档链接）、
> LumiRSS 侧入口、诚实状态标注、可验证证据与测试。事实来源：本仓库代码
> （file:symbol）、官方 FreshRSS 文档（freshrss.github.io/FreshRSS/en/，
> 2026-09 核对）、部署 pin。配置见 [configuration](/configuration)。

## 部署版本

- `docker-compose.yml`、`docker-compose.prod.yml`、
  `e2e/stack/docker-compose.e2e.yml` 三处均 pin
  **`freshrss/freshrss:1.29.1`**。本矩阵按 1.29.x 能力核对。

## 读法

- 状态取值：**原生实现**（Lumi BFF/Web 有真实可用通道）、**委托**
  （FreshRSS 原生域提供，Lumi 不复制也不经 API 暴露）、
  **未提供**（Lumi 无通道，注明原因）。
- 「证据」列引用代码时格式为 `file:symbol`（BFF 源码位于
  `services/bff/src/lumirss/`，测试位于 `services/bff/tests/`）。
- LumiRSS 架构不变量（FreshRSS 拥有 RSS 域状态、浏览器不接触上游凭据）
  见 [architecture](/architecture)。

## 覆盖矩阵

| 能力域 | FreshRSS 支持（版本/文档） | LumiRSS 入口 | 状态 | 证据 | 测试 |
|---|---|---|---|---|---|
| 订阅与分类 | 1.29 支持分类/订阅管理（[Subscriptions](https://freshrss.github.io/FreshRSS/en/users/04_Subscriptions.html)）；greader API 含 `subscription/list`、`subscription/edit`（订阅/退订，官方示例即退订）（[GReader API](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)） | `GET/POST/DELETE /api/v1/subscriptions`、`GET /api/v1/categories`、`PATCH /api/v1/subscriptions/{ref}`（移动/新建分类）、`PATCH /api/v1/categories/{id}`（重命名）；Web「订阅中心」 | 原生实现（单分类模型，greader `categories[0]`） | `adapters/freshrss_control.py:FreshRSSControlAdapter.subscribe/unsubscribe/move_category/rename_category`；`routers/subscriptions.py` | `tests/test_freshrss_control.py`、`tests/test_subscriptions_route.py`、`tests/test_f004_f005_f006_subscriptions.py` |
| OPML 导入/导出 | 1.29 支持 OPML 导入导出（[主特性页](https://freshrss.github.io/FreshRSS/en/)、[Subscriptions](https://freshrss.github.io/FreshRSS/en/users/04_Subscriptions.html)） | `POST /api/v1/opml/import/preview` → `POST /api/v1/opml/import`（合并式）、`GET /api/v1/opml/export`；Web 设置→订阅与来源 + 订阅页导入对话框 | 原生实现（经 BFF 代理，浏览器不接触 FreshRSS 凭据） | `services/bff/src/lumirss/opml.py:OpmlService`；`adapters/freshrss_control.py:FreshRSSControlAdapter.export_opml`；`routers/opml.py` | `tests/test_opml.py`、`tests/test_f002_opml_selective.py`、`tests/test_f003_opml_export_selection.py`；Web `apps/web/src/__tests__/opml-import.test.tsx` |
| 文章已读/收藏状态 | 1.29 支持已读/收藏（[主特性页](https://freshrss.github.io/FreshRSS/en/)）；greader `edit-tag`（Lumi 实测 1.29.1） | `PATCH /api/v1/entries/{entry_ref}/state`（**set 语义，非 toggle**；打开文章不自动已读） | 原生实现 | `adapters/freshrss.py:FreshRSSAdapter.set_entry_state`；`routers/entries.py:entry_state` | `tests/test_entry_state.py`、`tests/test_entry_adapter.py` |
| 文章列表/流 | greader `stream/contents`（reading-list / feed / label 流，官方示例）（[GReader API](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)） | `GET /api/v1/entries`（all/unread/starred 视图，feed/分类流，不透明游标分页） | 原生实现（过滤在上游 `it` 参数完成） | `adapters/freshrss.py:FreshRSSAdapter.list_entries`（`_request_stream`/`_request_category_stream`） | `tests/test_entries_route.py`、`tests/test_entries_pagination.py`、`tests/test_entry_adapter.py` |
| 全文搜索（经 API） | FreshRSS UI 有搜索/过滤（[主特性页](https://freshrss.github.io/FreshRSS/en/)）；官方 greader API 文档**未记载**专门 search 端点（仅 `subscription/list`、`unread-count`、`tag/list`、`token`、`stream/contents`、`subscription/edit`） | `GET /api/v1/search` + `POST /api/v1/search/rebuild`：Lumi **本地派生投影**（`list_entry_documents` 限界采集 → `html_to_text` 全文），不依赖 FreshRSS API 搜索 | 原生实现（Lumi 投影，刻意不走上游搜索） | `services/bff/src/lumirss/search_index.py:SearchIndexService`；`adapters/freshrss.py:FreshRSSAdapter.list_entry_documents`；`routers/search.py` | `tests/test_search_index.py`、`tests/test_search_sync_lifecycle.py`、`tests/test_f017_search_builder.py` |
| 刷新调度（全局） | 1.29 支持 cron 自动更新（[FeedUpdates](https://freshrss.github.io/FreshRSS/en/admins/08_FeedUpdates.html)、[Refreshing feeds](https://freshrss.github.io/FreshRSS/en/users/09_refreshing_feeds.html)） | 部署层：`docker-compose.yml` / `docker-compose.prod.yml` 的 FreshRSS 容器 `CRON_MIN`（唯一调度拥有者）；BFF 无刷新调度 | 委托（FreshRSS 容器 cron；部署配置承担） | `docker-compose.yml:CRON_MIN`（`13,43`）；`docker-compose.prod.yml` | 无 BFF 测试（部署配置，非代码路径） |
| 刷新调度（每源频率） | 1.29 支持每源 "Do not automatically refresh more often than"（TTL，下限 15 分钟，默认在 Archiving 配置）（[Refreshing feeds](https://freshrss.github.io/FreshRSS/en/users/09_refreshing_feeds.html)） | 无 Lumi 入口 | **未提供**（greader API 无每源 TTL 通道；属 FreshRSS 原生 UI 域——**委托候选**，可经 P09 原生界面入口操作） | 无对应 BFF 代码（`adapters/freshrss_control.py` 仅订阅/分类/OPML） | 无 |
| 保留/清理策略（retention/purge） | 1.29 支持全局→分类→每源三级 Archiving/purge 策略 + "Purge now" + `cli/purge.php`（[Configuration#archiving](https://freshrss.github.io/FreshRSS/en/users/05_Configuration.html)） | 无 Lumi 入口（FreshRSS 文章保留完全由上游策略拥有） | **未提供**（FreshRSS admin/UI 域；Lumi 只对自己的**派生数据**有保留策略——`ai_versions`/`task_log` 清理，用户内容永不触碰） | `services/bff/src/lumirss/storage_retention.py`（F114，仅派生数据）；`docs:users/05_Configuration.md#archiving` | `tests/test_search_sync_lifecycle.py`（投影侧）；retention 见 F114 对应测试 |
| 用户管理 | 1.29 多用户 + admin 用户管理页（[主特性页](https://freshrss.github.io/FreshRSS/en/)、[User management](https://freshrss.github.io/FreshRSS/en/admins/12_User_management.html)） | Lumi 自有账户体系：邀请→`/activate` 激活；另有可选公开注册（实例级开关，默认关闭——[architecture](/architecture#accounts)）；FreshRSS 用户由 operator 预置进池（`scripts/freshrss_pool.sh` + `POST` admin pool API），激活时经 `bind_freshrss_account` 写入该用户绑定 | 原生实现（Lumi 账户）+ 委托（FreshRSS 侧用户创建/管理属 operator/admin UI 域） | `services/bff/src/lumirss/accounts_store.py:AccountsStore`；`services/bff/src/lumirss/control_resources.py:bind_freshrss_account`；`routers/admin.py:pool_add`；`scripts/freshrss_pool.sh` | `tests/test_auth_sessions.py`（会话/激活）、`tests/test_admin_system.py`、`tests/test_admin_role_api.py` |
| API 访问（greader） | 1.29 提供 Google Reader 兼容 API（ClientLogin + `GoogleLogin auth` 头；需在 UI 启用并生成每用户 API password）（[GReader API](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)） | 全部 FreshRSS 读写经此 API：`FreshRSSSession`（ClientLogin/auth token/action token 仅进程内存）；API password 存每用户 secrets 文件（0600），永不进浏览器 | 原生实现（作为 Lumi 唯一上游通道；凭据零暴露） | `adapters/freshrss.py:FreshRSSSession._get_auth_token/_get_action_token`；`services/bff/src/lumirss/deps.py:_build_user_adapter` | `tests/test_freshrss_adapter.py`、`tests/test_freshrss_native_url.py` |
| 扩展（extensions） | 1.29 支持扩展系统（[Extensions](https://freshrss.github.io/FreshRSS/en/admins/15_extensions.html)） | 无 Lumi 入口；operator 可在 FreshRSS 原生界面安装/管理 | **委托**（greader API 无扩展通道；原生 UI 域） | 无对应 BFF 代码（诚实缺席） | 无 |
| 分享（sharing services） | 1.29 支持分享到外部服务（Clipboard/Email/Buffer/Diaspora 等）（[Sharing services](https://freshrss.github.io/FreshRSS/en/users/08_sharing_services.html)） | 无 Lumi 入口（Lumi 侧另有自有导出通道：Obsidian handoff / 库导出，**不是** FreshRSS 分享域） | **未提供**（委托候选，可经原生界面使用） | `services/bff/src/lumirss/obsidian_handoff.py`（Lumi 自有导出，非分享）；无分享相关 BFF 代码 | 无 |
| 标签/Label（条目级） | greader 有 `tag/list`（官方示例）；FreshRSS UI 支持条目标签/labels | RSS 条目不透传 FreshRSS labels（`set_entry_state` 仅 read/star）；Lumi 另有**自有**统一标签系统（Lumi-owned items：`rss:`/`library:` ItemRef） | **未提供**（FreshRSS 条目 label 无 Lumi 通道；Lumi 标签是独立自有域，非同一数据） | `services/bff/src/lumirss/tags.py:TagStore`（自有域）；`adapters/freshrss.py:FreshRSSAdapter.set_entry_state`（仅 read/star）；`adapters/freshrss.py:CATEGORY_PREFIX`（分类≠标签） | `tests/test_tag_merge.py`、`tests/test_tags_graph.py`（自有标签域） |
| 未读计数 | greader `unread-count`（官方示例）；UI 侧边显示各源未读数（[Main view](https://freshrss.github.io/FreshRSS/en/users/03_Main_view.html)） | BFF 不消费 `unread-count` 端点；Web 侧栏有「未读」**视图**（过滤流）但无未读总数徽标 | **未提供**（无依赖场景：过滤流已覆盖未读阅读；如需计数徽标可后续经 `unread-count` 端点实现） | `adapters/freshrss.py`（仅 `_UNREAD_FILTER` 作 `it` 过滤，无 unread-count 调用）；`apps/web/src/components/Sidebar.tsx:selectView('unread')` | 无 |

## 委托入口（P09）

对上表「委托/未提供（委托候选）」的能力，Lumi 提供一个诚实的逃生入口：

- **BFF**：`GET /api/v1/freshrss/native-url`（会话/内部令牌中间件统一
  门禁，用户级）。响应**恰好** `{origin, username}`：
  - `origin` = 当前用户绑定里**浏览器可达**的 `public_url`（激活/迁移时
    写入）。内部 `FRESHRSS_BASE_URL`（可能是 Docker 主机名）**永不回显**
    ——与 `GET /api/v1/freshrss-ui` 同一安全决策，且刻意不从其派生；
  - `username` = 该账户在 FreshRSS 侧的登录名（让原生界面里的身份可识别）；
  - 响应模型没有承载凭据的字段：API password / greader token 契约上不可
    能出现在响应里；
  - 绑定未完成或未配置浏览器可达地址 → `409
    freshrss_native_url_unavailable`（诚实待定，不给假链接）。
- **Web**：设置 → 订阅与来源 → FreshRSS 卡片 →「高级：打开 FreshRSS
  原生界面」（新标签页打开，`rel="noopener noreferrer"`，标注
  「委托：由 FreshRSS 提供（账号 …）」）；绑定待定 → 显示待定文案。

## 开放缺口（Open Gaps）

1. **每源刷新频率（TTL）**：FreshRSS 支持，greader API 无通道，Lumi
   未提供 —— 目前经委托入口在原生界面设置。
2. **文章保留/清理（purge）**：FreshRSS admin/UI 域，Lumi 未提供。
3. **FreshRSS 条目标签（labels）**：Lumi 不透传；Lumi 自有标签域与其
   互不相通。
4. **分享服务**：未提供（委托候选）。
5. **未读计数**：`unread-count` 端点未消费，无计数徽标。

## RSSHub 能力族覆盖（R22）

> 与 FreshRSS 矩阵同构（H01–H20 与 upstream-feature-matrix.html 表 1 同一
> 框架编号）。事实来源：本仓库代码（file:line）、pinned image 路由快照、
> RSSHub 官方文档（docs.rsshub.app，文档线索）。

## 部署版本

- `docker-compose.yml:19`、`docker-compose.prod.yml:133`、
  `e2e/stack/docker-compose.e2e.yml:110` 均按 digest pin
  **`diygod/rsshub@sha256:387fd32ee2d8789154dcf6446a52365976e768d9ede1a7c1e610cf4da9d89fbc`**。
  该 digest 同时是 `rsshub_routes.generated.json` 的 `_meta.rsshubImage`
  锚点，`services/bff/tests/test_rsshub_catalog_upstream.py` 断言两者一致。

## 读法

- 状态取值：**完整接入**（BFF 端点 + Web 入口双证据）、**部分接入**
  （有真实通道但刻意/暂时不覆盖上游全量）、**未接入**（无 Lumi 通道）、
  **不适用**（Lumi 架构不映射的上游域）。Lumi 自有扩展能力（收藏/最近
  使用、参数方案、params-diff、强制刷新、管理员使用聚合等）并入相关
  主题行的证据列，不占框架行。
- 证据格式 `file:line`（BFF 源码 `services/bff/src/lumirss/`，Web
  `apps/web/src/components/`，测试 `services/bff/tests/`）。
- RSSHub 定位（架构不变量）：**feed 生成器，不是条目数据库**；浏览器
  永不直连 RSSHub；订阅 URL 用 FreshRSS 容器视角构造（0008）。
- **目录存在 ≠ 实测可用**：路由快照是 pinned image 元数据的 vendored
  副本（131 路由），网络可用性按导入源与代表样本执行——H04 导入
  apply 内逐项真实验证即是测试点；curated 目录 14 条于 2026-09-01 对
  pinned 实例逐条实测（HTTP 200 + 可解析 feed）。

## 覆盖矩阵

| 能力族 | RSSHub 支持（上游事实/文档） | LumiRSS 入口 | 状态 | 证据 | 测试 |
|---|---|---|---|---|---|
| H01 实例连接 | 实例以 env 配置（base URL；[docs.rsshub.app](https://docs.rsshub.app/)，文档线索） | `RssHubSettings`（RSSHUB_BASE_URL/RSSHUB_FRESHRSS_BASE_URL；`rsshub.py:load_settings` L494-508 缺失/非法 → `RssHubNotConfigured` L155）；共享 client `main.py` L318-319；compose rsshub 服务 + healthcheck（`docker-compose.yml:18-30`）；Web `settings/RssHubAutoConfigCard.tsx` | 完整接入 | `rsshub.py` L155/L494-508；`main.py:318`；`docker-compose.yml:18` | `tests/test_rsshub_gate.py` |
| H02 路由目录 | 上游有数百命名空间的社区路由目录（[docs.rsshub.app](https://docs.rsshub.app/)，文档线索；pinned image routes.json → 快照，见 upstream-feature-matrix.html 表 2） | `GET /api/v1/rsshub/routes`（curated 14 条 + 参数元数据）：`rsshub.py:CATALOG`（L255）、`list_routes`（L509）、`routers/rsshub.py` L113；全量快照 13 命名空间/131 路由用于 H04 匹配；Lumi 扩展：收藏/最近使用 `routers/rsshub.py` L373/L385/L403/L416（`rsshub_route_store.py:mask_params` 哨兵）；Web `add-source/RssHubTab.tsx` L54 | 部分接入（刻意 allowlist：curated 14/131，2026-09-01 逐条实测；扩展需改代码） | `rsshub.py` L255/L509；`routers/rsshub.py` L113/L373-L416 | `tests/test_rsshub.py`、`test_n021_rsshub_favorites_recent.py`、`test_rsshub_catalog_upstream.py` |
| H03 实例自动识别 | 实例可达性（/healthz） | `GET /api/v1/rsshub/detect`：只探测受限候选（configured/compose-dns/host-loopback 三处，2s；绝无 LAN 扫描）；Web `RssHubAutoConfigCard.tsx` L53 | 完整接入 | `routers/rsshub.py` L727 | `tests/test_rsshub_gate.py` |
| H04 OPML 导入自动采用（R18） | 非 RSS 源经 RSSHub 转换（RSSHub 定位：feed 生成器） | `rsshub_import_flow.py:plan`（L101 零网络零写入）/`apply`（L134；`_validate` L349 先实测再订阅，MAX_VALIDATIONS=30 L55）；`rsshub_match.py:classify_feed_url`（L239 四分类）+ `match_source`；`rsshub_routes_data.py:match_concrete_path`（L197 上界 8 匹配）；`routers/opml.py` L284/L300/L371/L381；Web `OpmlImportFlow.tsx` L281、`SourceStatsDrawer.tsx` L264、`api/client.ts` L1841-L1889 | 完整接入（诚实边界：不自动退订旧源；条目状态不可跨源迁移） | `rsshub_import_flow.py`、`rsshub_match.py`、`routers/opml.py` | `tests/test_r18_rsshub_import.py`、Web `__tests__/r18-rsshub-import.test.tsx` |
| H05 路由溯源 | （Lumi 域） | `GET /api/v1/rsshub/routes/{route_key}/my-sources`（本人作用域；feed URL 反向匹配脱敏签名，服务端不触真实凭据）；`rsshub.py:match_route_path`（L426）；Web `RssHubTab.tsx` useRssHubRouteMySources | 完整接入 | `routers/rsshub.py` L961；`rsshub.py` L426 | `tests/test_n021_rsshub_favorites_recent.py` |
| H06 路径参数 | 路由路径含参数段（快照 `parameters` 元数据；[docs.rsshub.app](https://docs.rsshub.app/)，线索） | 服务端构造：`rsshub.py:build_path`（L450 pattern fullmatch + 逐段 URL 编码 + 结构检查，路径注入不可行）、`_template_pattern`（L413）；运营态表单面 `routers/new207_rsshub_form.py` L58/L67/L82/L174（schema/validate/apply/uses）；Lumi 扩展：参数方案 `routers/rsshub.py` L1077-L1133（cap 20/用户）+ params-diff L556（`extract_entry_titles` L675/`diff_title_sets` L694，严格只读）；Web `RssHubTab.tsx` 参数表单、`new201/SourceOpsDialog.tsx` L758、`rsshub-route-params-dialog.tsx` | 完整接入 | `rsshub.py` L413/L450；`routers/new207_rsshub_form.py`；`routers/rsshub.py` L556/L1077-L1133 | `tests/test_rsshub.py`、`test_new207_rsshub_form.py`、`test_n030_rsshub_param_presets.py` |
| H07 通用参数（limit/mode/key） | RSSHub 支持路由通用 query 参数（[docs.rsshub.app](https://docs.rsshub.app/)，线索） | 不支持：`build_path`（`rsshub.py` L455-458）对未声明键显式拒绝（`RssHubInvalidParameters`）；预览仅拼 path（L519/L548），无 query string 透传 | **未接入**（诚实边界：需通用参数的源经原生界面直订或后续扩展白名单） | `rsshub.py` L455-458 | 无 |
| H08 过滤参数（filter/filter_title 等） | RSSHub 支持过滤参数（[docs.rsshub.app](https://docs.rsshub.app/)，线索） | 不支持：同 H07，参数白名单只含路由声明键；Lumi 时间线过滤走自有域（`feed_filters.py`，见 FreshRSS 矩阵对应能力行） | **未接入** | `rsshub.py` L455-458 | 无 |
| H09 Feed 预览（非变更） | RSSHub 对路由路径返回 RSS/Atom 文档 | `POST /api/v1/rsshub/preview`（origin 锁定 + 有界 body + 重定向不出源；alreadySubscribed 预检）；Web `RssHubTab.tsx` → `add-source/PreviewStage.tsx` | 完整接入 | `rsshub.py:RssHubService.preview`（L522）；`routers/rsshub.py` L182 | `tests/test_rsshub.py` |
| H10 站点/路由凭据库 | 路由所需站点凭据（Cookie/token/API key；[docs.rsshub.app](https://docs.rsshub.app/)，线索） | `GET/POST/PATCH/PUT/DELETE /api/v1/rsshub/credentials`（values write-only，仅 configured 旗标可读；加凭据绝不臆造路由）；Web `RssHubAutoConfigCard.tsx` | 完整接入 | `routers/rsshub.py` L770-L819 | `tests/test_rsshub_control.py` |
| H11 管理员配置中心 | RSSHub 实例 env（缓存/代理/上游凭据等；[docs.rsshub.app](https://docs.rsshub.app/)，线索） | `GET/PATCH /api/v1/rsshub/config`（allow-list 非密值；restartRequired 如实上报）、`PUT/DELETE config/secrets/{key}`（write-only）、`POST config/apply`；Lumi 扩展：管理员路由使用聚合 `GET /api/v1/admin/rsshub/routes/{route_key}/usage`（响应仅计数，绝不返回他人订阅标题/URL/用户名）；Web `settings/RssHubControlCenter.tsx` | 部分接入（配置中心完整；使用聚合**后端有但 UI 缺失**——Web 无调用组件，仅生成类型） | `rsshub_control.py:RssHubControlStore`（L238）、`config_view`（L354）、`set_secret`（L324）；`routers/rsshub.py` L664/L677/L866/L876/L884、L1005/`_admin_guard` L1139 | `tests/test_rsshub_control.py` |
| H12 配置生效 | 实例配置以 env 应用（[docs.rsshub.app](https://docs.rsshub.app/)，线索） | `GET /api/v1/rsshub/config/export`（secrets 不回显）、`POST config/env-file`（服务端写 0700 目录 + 0600 文件，响应仅计数；宿主机 `services/bff/scripts/apply_rsshub_config.py` 应用）；`rsshub_control.py:export_env`（L389）；Web `RssHubControlCenter.tsx` L329、`RssHubAutoConfigCard.tsx` | 完整接入 | `routers/rsshub.py` L696/L825；`rsshub_control.py` L389 | `tests/test_rsshub_control.py` |
| H13 缓存 TTL | 实例 `CACHE_EXPIRE` 控制路由输出缓存（[docs.rsshub.app](https://docs.rsshub.app/)，线索） | Lumi 预览缓存 `RssHubPreviewCache`（`rsshub.py` L109：per-user TTL 300s + LRU 50；命中不重抓/不记时间线/不 touch 最近使用 `routers/rsshub.py` L219-230）；强制刷新 `POST /api/v1/rsshub/refresh`（L444 令牌桶 6 次/分/用户，429+Retry-After；L502 敏感哨兵路由拒绝）= 缓存旁路；实例 `CACHE_EXPIRE`（`rsshub_control.py` L126）经 H11/H12 配置面管理；Web `RssHubTab.tsx` useRssHubRefreshMutation | 完整接入 | `rsshub.py` L109；`routers/rsshub.py` L219-230/L444/L480/L502 | `tests/test_n027_rsshub_preview_cache.py` |
| H14 超时与重试 | （Lumi 域：对 RSSHub 调用的边界） | 共享 client `main.py` L318-319 `Timeout(10.0, connect=5.0)`；`rsshub.py:_send`（L645-655）httpx.HTTPError → `FAILURE_RSSHUB_UNREACHABLE`（N026 稳定分类，不与上游拒绝混叠）；无自动重试（单次尝试，失败如实入时间线） | 部分接入（超时+分类完整；重试为显式不做） | `main.py:318`；`rsshub.py` L645-655 | `tests/test_n026_rsshub_failure_classes.py` |
| H15 代理浏览器依赖 | 路由可能需要登录/Cookie/浏览器渲染/额外服务（上游路由实现事实） | 目录下发 `requires` 四元组（True/False/None 三态诚实，未知绝不冒充「不需要」）：`rsshub.py:RssHubRequires`（L209）、`requires_json`（L222）；`routers/rsshub.py` L148；实例 `PROXY_URI`（`rsshub_control.py` L135）/`PUPPETEER_WS_ENDPOINT`（L142）/`ACCESS_KEY`（L137）配置面；Web `rsshub-requires-chips.tsx` | 完整接入（curated 静态知识，非运行时探测） | `rsshub.py` L209/L222；`rsshub_control.py` L135/L137/L142 | `tests/test_n023_rsshub_requires.py` |
| H16 运行状态 | 上游错误面（不可达/上游拒绝/限流等） | `GET /api/v1/rsshub/routes/history`（每路由 last 20）+ `_record_run`（L321）+ N026 稳定失败分类（`rsshub.py` L90-97）+ 0 条目诚实提示 `ZERO_ENTRY_HINT`（L669）；Web `rsshub-route-health-card.tsx` | 完整接入 | `routers/rsshub.py` L321/L427；`rsshub.py` L90-97/L669 | `tests/test_n025_rsshub_route_runs.py`、`test_n026_rsshub_failure_classes.py` |
| H17 版本 digest | 镜像升级可能改变路由行为（digest pin 策略） | `docker-compose.yml:19`/`docker-compose.prod.yml:133`/`e2e/stack/docker-compose.e2e.yml:110` digest pin + 快照 `_meta.rsshubImage` 锚定 + `test_rsshub_catalog_upstream.py` L27 一致性门禁 + 再生成契约 `services/bff/scripts/export_rsshub_routes.py`；升级兼容检查（N028）`rsshub_upgrade_check.py:run_upgrade_check`（L183）+ `routers/rsshub.py` L1164/L1190（admin-gated；≤12 条真实 preview；targetImage 恒记 pending——Lumi 无 Docker 视角；keep-last-3） | 部分接入（digest 锚定完整；N028 升级检查**后端有但 UI 缺失**，操作路径暂为管理员 API） | `docker-compose.yml:19`；`rsshub_upgrade_check.py` L183；`routers/rsshub.py` L1164/L1190 | `tests/test_rsshub_catalog_upstream.py`、`test_n028_rsshub_upgrade_check.py` |
| H18 访问保护 | RSSHub 支持 `ACCESS_KEY` 访问密钥保护路由（[docs.rsshub.app](https://docs.rsshub.app/)，线索） | 实例发布面回环 only（`docker-compose.yml:23` 127.0.0.1:1200；allinone 内部 127.0.0.1:12001）；浏览器永不直连（0008 + `test_rsshub_gate.py` 负向契约）；`ACCESS_KEY`（`rsshub_control.py` L137）write-only 管理；但 BFF 请求不自动附带 ACCESS_KEY（`rsshub.py:_HEADERS` L83 仅 UA）——受保护路由的抓取会归入 auth_failure 分类 | 部分接入（部署边界+管理面完整；受保护路由取数未打通） | `docker-compose.yml:23`；`rsshub_control.py` L137；`rsshub.py` L83 | `tests/test_rsshub_gate.py` |
| H19 职责边界 | RSSHub 生成 feed，由订阅方抓取；不存条目状态 | 订阅闭环：preview 返回 `RSSHUB_FRESHRSS_BASE_URL + path` 作为订阅地址（`rsshub.py` L562）→ `POST /api/v1/subscriptions` 入 FreshRSS（浏览器不直连 RSSHub）；快照仅路由元数据非条目数据（`rsshub_routes_data.py:SNAPSHOT_PATH` L48）；Web `RssHubTab.tsx` useSubscribeMutation | 完整接入 | `rsshub.py` L562 | `tests/test_rsshub_gate.py`（负向契约） |
| H20 单容器降级 | RSSHub 可选部署；allinone 内置 | `docker-compose.allinone.yml` 单容器内置 RSSHub（loopback 127.0.0.1:12001；RSSHUB_*_BASE_URL 被 compose override 为回环地址）；未配置 → `RssHubNotConfigured` 诚实报错（`routers/rsshub.py` L126）；导入 plan/apply 如实降级（`rsshub_import_flow.py` L357-358 `rsshub_not_configured`）；原生 RSS 全功能不受影响 | 完整接入 | `docker-compose.allinone.yml`；`routers/rsshub.py` L126；`rsshub_import_flow.py` L357-358 | `tests/test_r18_rsshub_import.py`（未配置分支） |

## 路由快照与再生成（R18 契约）

1. 升 `docker-compose.yml`（及 prod、e2e）的 `diygod/rsshub@sha256:` pin；
2. `docker pull` 该镜像并重建 dev rsshub 容器；
3. 按需扩充 `services/bff/scripts/export_rsshub_routes.py` 的
   `NAMESPACES`（匹配覆盖是显式可审列表，永远不是「上游全部」）；
4. `uv run python scripts/export_rsshub_routes.py`，快照与 pin 一起提交
   （`test_rsshub_catalog_upstream.py` 会做一致性门禁）。

## 开放缺口（Open Gaps）

1. **H07/H08 通用参数与过滤参数未接入**：`build_path` 参数白名单只含
   路由声明键，RSSHub 路由级 query 参数（limit/mode/filter 族）无透传
   通道；需要时经原生界面直订或扩展白名单。
2. **H11/H17 部分子能力无 Web 入口**：管理员路由使用聚合与 N028 升级
   兼容检查 BFF + 测试齐备，管理界面未挂接（暂为 API 操作路径）。
3. **H18 受保护路由取数未打通**：ACCESS_KEY 可经配置中心管理，但 BFF
   预览请求不自动签名——受保护路由预览会失败并如实归入 auth_failure。
4. **H14 无自动重试**：RSSHub 抓取单次尝试 + 稳定失败分类；有界重试
   仅用于安全幂等操作的约定下，此处显式不重试。
5. **curated 目录覆盖**：H02（14 条 curated / 131 路由快照）是刻意白
   名单；扩大覆盖 = 改 `CATALOG` / `NAMESPACES` +
   `DOMAIN_NAMESPACE_MAP`，且每条新增应对 pinned 实例做一次真实可用性
   验证。
6. **requires 元数据人工维护**：依赖标注是 curated 静态知识（三态含
   「未知」），不随上游路由实现自动更新。
7. **RSSHub 官方文档深链**：本矩阵对 docs.rsshub.app 仅引文档站根作
   线索（路由级事实以 pinned image 快照为准——快照即上游证据）。
