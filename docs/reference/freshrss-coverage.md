# FreshRSS Capability Coverage Matrix

> P09：FreshRSS 能力覆盖矩阵与委托边界。行 = FreshRSS 能力域；每行给出
> FreshRSS 侧支持情况（含官方文档链接）、LumiRSS 侧入口、诚实状态标注、
> 可验证证据与测试。事实来源：本仓库代码（file:symbol）、官方 FreshRSS
> 文档（freshrss.github.io/FreshRSS/en/，2026-09 核对）、部署 pin。
> 相关配置见 [configuration.md](configuration.md)，测试门禁见
> [testing.md](testing.md)。

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
  见 [explanation/architecture.md](../explanation/architecture.md)。

## 覆盖矩阵

| 能力域 | FreshRSS 支持（版本/文档） | LumiRSS 入口 | 状态 | 证据 | 测试 |
|---|---|---|---|---|---|
| 订阅与分类 | 1.29 支持分类/订阅管理（[Subscriptions](https://freshrss.github.io/FreshRSS/en/users/04_Subscriptions.html)）；greader API 含 `subscription/list`、`subscription/edit`（订阅/退订，官方示例即退订）（[GReader API](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)） | `GET/POST/DELETE /api/v1/subscriptions`、`GET /api/v1/categories`、`PATCH /api/v1/subscriptions/{ref}`（移动/新建分类）、`PATCH /api/v1/categories/{id}`（重命名）；Web「订阅中心」 | 原生实现（单分类模型，greader `categories[0]`） | `adapters/freshrss_control.py:FreshRSSControlAdapter.subscribe/unsubscribe/move_category/rename_category`；`routers/subscriptions.py` | `tests/test_freshrss_control.py`、`tests/test_subscriptions_route.py`、`tests/test_f004_f005_f006_subscriptions.py` |
| OPML 导入/导出 | 1.29 支持 OPML 导入导出（[主特性页](https://freshrss.github.io/FreshRSS/en/)、[Subscriptions](https://freshrss.github.io/FreshRSS/en/users/04_Subscriptions.html)） | `POST /api/v1/opml/import/preview` → `POST /api/v1/opml/import`（合并式）、`GET /api/v1/opml/export`；Web 设置→订阅与来源 + 订阅页导入对话框 | 原生实现（经 BFF 代理，浏览器不接触 FreshRSS 凭据） | `lumirss/opml.py:OpmlService`；`adapters/freshrss_control.py:FreshRSSControlAdapter.export_opml`；`routers/opml.py` | `tests/test_opml.py`、`tests/test_f002_opml_selective.py`、`tests/test_f003_opml_export_selection.py`；Web `apps/web/src/__tests__/opml-import.test.tsx` |
| 文章已读/收藏状态 | 1.29 支持已读/收藏（[主特性页](https://freshrss.github.io/FreshRSS/en/)）；greader `edit-tag`（Lumi 实测 1.29.1） | `PATCH /api/v1/entries/{entry_ref}/state`（**set 语义，非 toggle**；打开文章不自动已读） | 原生实现 | `adapters/freshrss.py:FreshRSSAdapter.set_entry_state`；`routers/entries.py:entry_state` | `tests/test_entry_state.py`、`tests/test_entry_adapter.py` |
| 文章列表/流 | greader `stream/contents`（reading-list / feed / label 流，官方示例）（[GReader API](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)） | `GET /api/v1/entries`（all/unread/starred 视图，feed/分类流，不透明游标分页） | 原生实现（过滤在上游 `it` 参数完成） | `adapters/freshrss.py:FreshRSSAdapter.list_entries`（`_request_stream`/`_request_category_stream`） | `tests/test_entries_route.py`、`tests/test_entries_pagination.py`、`tests/test_entry_adapter.py` |
| 全文搜索（经 API） | FreshRSS UI 有搜索/过滤（[主特性页](https://freshrss.github.io/FreshRSS/en/)）；官方 greader API 文档**未记载**专门 search 端点（仅 `subscription/list`、`unread-count`、`tag/list`、`token`、`stream/contents`、`subscription/edit`） | `GET /api/v1/search` + `POST /api/v1/search/rebuild`：Lumi **本地派生投影**（`list_entry_documents` 限界采集 → `html_to_text` 全文），不依赖 FreshRSS API 搜索 | 原生实现（Lumi 投影，刻意不走上游搜索） | `lumirss/search_index.py:SearchIndexService`；`adapters/freshrss.py:FreshRSSAdapter.list_entry_documents`；`routers/search.py` | `tests/test_search_index.py`、`tests/test_search_sync_lifecycle.py`、`tests/test_f017_search_builder.py` |
| 刷新调度（全局） | 1.29 支持 cron 自动更新（[FeedUpdates](https://freshrss.github.io/FreshRSS/en/admins/08_FeedUpdates.html)、[Refreshing feeds](https://freshrss.github.io/FreshRSS/en/users/09_refreshing_feeds.html)） | 部署层：`docker-compose.yml` / `docker-compose.prod.yml` 的 FreshRSS 容器 `CRON_MIN`（唯一调度拥有者）；BFF 无刷新调度 | 委托（FreshRSS 容器 cron；部署配置承担） | `docker-compose.yml:CRON_MIN`（`13,43`）；`docker-compose.prod.yml` | 无 BFF 测试（部署配置，非代码路径） |
| 刷新调度（每源频率） | 1.29 支持每源 "Do not automatically refresh more often than"（TTL，下限 15 分钟，默认在 Archiving 配置）（[Refreshing feeds](https://freshrss.github.io/FreshRSS/en/users/09_refreshing_feeds.html)） | 无 Lumi 入口 | **未提供**（greader API 无每源 TTL 通道；属 FreshRSS 原生 UI 域——**委托候选**，可经 P09 原生界面入口操作） | 无对应 BFF 代码（`adapters/freshrss_control.py` 仅订阅/分类/OPML） | 无 |
| 保留/清理策略（retention/purge） | 1.29 支持全局→分类→每源三级 Archiving/purge 策略 + "Purge now" + `cli/purge.php`（[Configuration#archiving](https://freshrss.github.io/FreshRSS/en/users/05_Configuration.html)） | 无 Lumi 入口（FreshRSS 文章保留完全由上游策略拥有） | **未提供**（FreshRSS admin/UI 域；Lumi 只对自己的**派生数据**有保留策略——`ai_versions`/`task_log` 清理，用户内容永不触碰） | `lumirss/storage_retention.py`（F114，仅派生数据）；`docs:users/05_Configuration.md#archiving` | `tests/test_search_sync_lifecycle.py`（投影侧）；retention 见 F114 对应测试 |
| 用户管理 | 1.29 多用户 + admin 用户管理页（[主特性页](https://freshrss.github.io/FreshRSS/en/)、[User management](https://freshrss.github.io/FreshRSS/en/admins/12_User_management.html)） | Lumi 自有账户体系：邀请→`/activate` 激活（无公开注册）；FreshRSS 用户由 operator 预置进池（`scripts/freshrss_pool.sh` + `POST` admin pool API），激活时经 `bind_freshrss_account` 写入该用户绑定 | 原生实现（Lumi 账户）+ 委托（FreshRSS 侧用户创建/管理属 operator/admin UI 域） | `lumirss/accounts_store.py:AccountsStore`；`lumirss/control_resources.py:bind_freshrss_account`；`routers/admin.py:pool_add`；`scripts/freshrss_pool.sh` | `tests/test_auth_sessions.py`（会话/激活）、`tests/test_admin_system.py`、`tests/test_admin_role_api.py` |
| API 访问（greader） | 1.29 提供 Google Reader 兼容 API（ClientLogin + `GoogleLogin auth` 头；需在 UI 启用并生成每用户 API password）（[GReader API](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)） | 全部 FreshRSS 读写经此 API：`FreshRSSSession`（ClientLogin/auth token/action token 仅进程内存）；API password 存每用户 secrets 文件（0600），永不进浏览器 | 原生实现（作为 Lumi 唯一上游通道；凭据零暴露） | `adapters/freshrss.py:FreshRSSSession._get_auth_token/_get_action_token`；`lumirss/deps.py:_build_user_adapter` | `tests/test_freshrss_adapter.py`、`tests/test_freshrss_native_url.py` |
| 扩展（extensions） | 1.29 支持扩展系统（[Extensions](https://freshrss.github.io/FreshRSS/en/admins/15_extensions.html)） | 无 Lumi 入口；operator 可在 FreshRSS 原生界面安装/管理 | **委托**（greader API 无扩展通道；原生 UI 域） | 无对应 BFF 代码（诚实缺席） | 无 |
| 分享（sharing services） | 1.29 支持分享到外部服务（Clipboard/Email/Buffer/Diaspora 等）（[Sharing services](https://freshrss.github.io/FreshRSS/en/users/08_sharing_services.html)） | 无 Lumi 入口（Lumi 侧另有自有导出通道：Obsidian handoff / 库导出，**不是** FreshRSS 分享域） | **未提供**（委托候选，可经原生界面使用） | `lumirss/obsidian_handoff.py`（Lumi 自有导出，非分享）；无分享相关 BFF 代码 | 无 |
| 标签/Label（条目级） | greader 有 `tag/list`（官方示例）；FreshRSS UI 支持条目标签/labels | RSS 条目不透传 FreshRSS labels（`set_entry_state` 仅 read/star）；Lumi 另有**自有**统一标签系统（Lumi-owned items：`rss:`/`library:` ItemRef） | **未提供**（FreshRSS 条目 label 无 Lumi 通道；Lumi 标签是独立自有域，非同一数据） | `lumirss/tags.py:TagStore`（自有域）；`adapters/freshrss.py:FreshRSSAdapter.set_entry_state`（仅 read/star）；`adapters/freshrss.py:CATEGORY_PREFIX`（分类≠标签） | `tests/test_tag_merge.py`、`tests/test_tags_graph.py`（自有标签域） |
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
