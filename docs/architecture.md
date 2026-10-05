# 架构（Architecture）

> 本文回答"系统现在如何实现"（HOW），是架构事实的唯一权威文档。
> 数据流、边界、数据归属、账户隔离、搜索机制、安全边界与已稳定的
> 架构决策结论都在这里。产品方向与未来计划见 [roadmap](/roadmap)；
> 运维操作见 [operations](/operations)；上游能力对照见 [upstreams](/upstreams)。

## 原则

1. **成熟引擎躲在 Lumi 自有边界之后。** FreshRSS 和 RSSHub 承担它们擅长的职责；Lumi 提供唯一日常产品界面。
2. **FreshRSS 拥有 RSS 域。** feeds / categories / entries / read / starred / subscriptions / OPML 只以 FreshRSS 为真源；Lumi SQLite 永不影子复制 RSS 数据（唯一例外是派生、可重建的搜索投影，见[全局搜索](#search)）。
3. **浏览器只与 Lumi BFF 通信**（`/api/v1/*` 相对路径），不直连 FreshRSS、RSSHub 或 AI Provider，不持有上游凭据。
4. **两平面分离。** 读取数据面与来源/服务控制面分离；控制面不改变读取路径。
5. **AI 可选且不阻塞。** AI 未配置或失败不影响阅读、状态写入与来源管理；GET 类 AI 端点绝不触发 Provider 调用。
6. **不可信内容以净化为最终边界。** 文章 HTML 经受控 transform 后必须通过 DOMPurify 才能进入 React。
7. **诚实状态。** read/star 写入用 set 语义；分页 cursor 与 `entryRef` 均为 opaque；打开文章不自动标为已读；所有网络状态都有 loading/empty/error UI。
8. **账户由服务端把关，数据按服务端身份隔离。** 默认邀请制：运营者经 `/admin` 发一次性限时邀请，受邀者在 `/activate` 自设用户名密码激活；可选公开注册是实例级开关、默认关闭、服务端强制（见[账户与数据分层](#accounts)）。

## 系统边界

| 部分 | 负责 | 不负责 |
|---|---|---|
| React Web | 展示、输入、导航、阅读反馈 | 保存业务事实、直连上游 |
| SwiftUI iOS（`apps/ios`） | 原生阅读（时间线/订阅/搜索/收藏/正文）、本地缓存 | 保存业务事实、直连上游、复制管理后台 |
| FastAPI BFF | 认证、业务规则、适配来源、组合结果、调用 AI | 重新实现 FreshRSS |
| FreshRSS | 订阅、条目、已读/收藏等 RSS 域事实 | 用户笔记、日报等 Lumi 自有内容 |
| Lumi SQLite | Lumi 自有内容、状态、引用、批准的可重建投影 | 复制整套 RSS 数据 |
| RSSHub | 非 RSS 来源 → 可消费 feed | 定义 UI 状态 |
| Caddy/Compose | 路由、进程与数据卷边界 | 业务语义 |

Web 与 iOS 消费**同一份** `/api/v1` 契约：FastAPI/Pydantic 是唯一真源，
Web 经 `pnpm api:generate` 生成 TS 类型；iOS 经
`apps/ios/scripts/filter_openapi.py` 从同一导出过滤子集后由
swift-openapi-generator 生成 Swift 客户端（漂移各有 CI 门禁）。iOS
认证复用浏览器同款 cookie 会话（URLSession 无 Origin 头，天然通过
CSRF 同源门；SameSite 属性对非浏览器存储无意义），会话 cookie 落
Keychain 而非 UserDefaults；无独立 token/刷新层——服务器会话有明确
有效期与撤销（logout/logout-all/管理台）。iOS 本地缓存是按服务器+
账户隔离的可重建副本（列表+正文，不含图片），不改变 FreshRSS 的
服务端权威地位。

## 数据流

```text
Native RSS / Atom ────────────────┐
Non-RSS → RSSHub-generated feed ──┤
                                  ▼
                               FreshRSS          ← RSS 域唯一真源
                                  ▼
                     FreshRSSAdapter / ControlAdapter
                                  ▼
                             FastAPI BFF  ──  Lumi SQLite（AI/设置/搜索投影）
                                  ▼
                    React Web / PWA  ·  SwiftUI iOS（apps/ios）
```

浏览器只信任 Lumi 契约，不感知上游实现细节。自动采集的拥有者是
FreshRSS 容器 cron（`LUMIRSS_FRESHRSS_CRON_MIN`）；BFF 没有第二套
抓取器。RSS 不自动更新时先查 cron（见 [operations](/operations#troubleshooting)）。

## 数据归属

| 数据 | 权威位置 |
| --- | --- |
| 身份 / 会话 / 邀请 / FreshRSS 池 / 审计 | Lumi 控制库（`lumi.sqlite`） |
| RSS feeds / categories / entries、read / starred、订阅 / 分类 / OPML（按账号隔离） | FreshRSS（每账号一个 FreshRSS 用户；订阅经 `FreshRSSControlAdapter` 管理） |
| API 来源配置、收件箱连接器与推送内容（`api_item`）、邮件桥 spool、书签 / 剪藏 / 快照、标签 / 工作区 / 收藏、Agent 会话（全部按账号隔离） | 每用户库（`users/<uid>/lumi.sqlite`） |
| Obsidian vault 内容 | vault 文件系统本身（Lumi 只保留单向、可删除重建的投影） |
| RSSHub 路由目录（Lumi 精选元数据） | BFF 静态 `CATALOG`（pinned 实例逐一验证） |
| RSSHub 期望/已应用配置、AI 非机密设置与 purpose 映射、AI 结果、便携设置（`app.settings`）、备份账本（全部按账号隔离） | 每用户库 |
| RSSHub 实例地址 | `RSSHUB_BASE_URL` / `RSSHUB_FRESHRSS_BASE_URL`（见 [configuration](/configuration)） |
| 设备本地设置（布局宽度、自定义字体、过滤规则、阅读外观） | 浏览器 localStorage / IndexedDB，不上传 |
| AI API keys、WebDAV 密码、RSSHub 机密、FreshRSS API 密码 | `secrets.json`（0600；per-user secrets 随用户库目录；刻意置于 DB 与备份之外） |
| RAG 向量 / 各类搜索投影 | 无主派生物：可重建、不进备份（library 资产本身是 owned 数据，进备份） |

## 账户与数据分层 {#accounts}

邀请制多账户的数据分层（已稳定决策，原 ADR 0005/0006 结论）：

- **控制库**（`LUMIRSS_DB_PATH`，即 `data/lumi.sqlite`）只存账户控制面：
  `users`（账号，bcrypt 口令哈希）、`invites`（一次性限时邀请，
  只存 token SHA-256）、`freshrss_pool`（预建账号登记与原子分配）、
  `instance_settings`（实例级开关）、`audit_log`、`token_owner_index` 与
  机器会话。
- **每用户业务库**：每个账号的全部业务数据位于
  `<data_dir>/users/<uid>/lumi.sqlite`，旁边是 per-user `secrets.json`；
  历史单用户 schema 与各 store 原样运行在用户库文件上。
- **身份只由服务端派生**：`RoutingDatabase` 经 ContextVar 把每个连接解析
  到当前请求的用户库（session 中间件或后台任务显式绑定）。没有验证身份
  的请求触碰私有库是硬错误——不存在匿名回退库；**前端声明的任何
  `user_id` 都不参与数据路由或授权**。
- **FreshRSS 账号是配给的，不是共享的**：运营者用
  `scripts/freshrss_pool.sh` 预建空账号入池，激活时原子分配；空池时账号
  照常可用、绑定诚实显示「待就绪」，绝无共享凭据回退。池运维见
  [operations](/operations#member-admin)。
- **可选公开注册默认关闭**（原 ADR 0006 结论）：开关
  `allow_public_registration` 只存控制库 `instance_settings`（迁移 0089），
  默认关闭；无 env、无 localStorage 覆盖；变更经
  `GET/PUT /api/v1/admin/registration-policy`（admin 会话）并落审计。
  开启后 `POST /api/v1/auth/register` 自助注册**只创建 member**（角色
  不可指定），FreshRSS 池原子分配、空池诚实 pending；关闭时统一 403
  `registration_disabled`（不泄露用户名是否存在），注册路径有限流与
  CSRF Origin 校验。开启注册不构成公共互联网加固，暴露面由运营者
  自行评估。

单一 ItemRef 注册表（原 ADR 0004 结论）：`rss:*` 与 `library:*` 引用只有
一个解析器（`itemref.py`）、一个注册表（`sources.py`）、一组解析器注册
（`deps.py`）；工作区、标签、收藏、图谱、统一搜索、RAG、Agent、稍后读
全部经注册表解析。写时验证引用可解析；悬空引用降级为 stale 视图，绝不
静默丢弃或伪造。跨表域写入单事务或显式补偿路径；schema 变更 forward-only。

## Obsidian：只读投影 + 唯一受限写面（原 ADR 0007 结论）

- **读面永久只读**：`/vault` 只读挂载 → SQLite 投影 → 渲染；投影模块
  （`obsidian.py`）零写调用；读面路径不出 vault 根。
- **唯一写面是独立挂载、显式 opt-in 的服务端导出**（overlay
  `docker-compose.obsidian-export.yml` + `LUMIRSS_OBSIDIAN_EXPORT_HOST_DIR`，
  容器内固定 `/vault-export`）：API `POST /api/v1/obsidian/export`，Web
  入口在阅读页「更多操作 → 导出到 Obsidian」。写入落在
  `<子目录>/<账户id>/` 下：tmp + `os.link`/`O_EXCL` 原子创建**绝不覆盖**
  既有文件、content-id 幂等（重复导出返回 `exists`）、每次写入前重做
  路径防御（符号链接逃逸一律拒绝）、配额 1 MB/文件 · 50 refs/批 ·
  64 MB/用户/日，全部写入落 per-user 账本审计。
- Lumi 永不删除或修改导出根里的任何东西；没有双向同步、没有自由写回。
  不叠加 overlay 的部署与该功能不存在完全等价。

## 部署拓扑（原 ADR 0008 结论）

默认四容器拓扑（web/Caddy、bff、freshrss、rsshub，GHCR 预构建镜像、
prebuilt-only）；可选**单容器拓扑**（`lumirss-allinone`：s6-overlay 监管
Caddy + BFF + FreshRSS php-fpm + RSSHub 同一容器）：

```text
Internet / private access
          ▼
   web (Caddy, 80/443)      ← 唯一发布端口的服务
   ├── /            → SPA 静态（try_files → index.html）
   └── /api/*       → bff:8000（lumi-data 卷；freshrss-data 只读卷）
                      ├─ FreshRSS（内网，healthcheck 门控 BFF 启动）
                      ├─ RSSHub（内网，非启动阻塞项）
                      └─ AI Provider（出站 HTTPS）
```

- **不变量跨拓扑成立**：compose 项目名（`lumirss-prod`）、命名卷
  （`lumi-data`、`freshrss-data`）与 uid 模型（BFF `lumirss` 10001 +
  补充组 `www-data`(33)，FreshRSS www-data 33）完全一致——两个拓扑
  互迁而数据卷原样通用，backup/restore 对两者都工作。
- 单容器天生 external-caddy-only（只发布 loopback 18080，TLS 由宿主
  反代终结）、仅应用会话认证、镜像 amd64-only、总内存 limit 默认
  1200m（空闲实测约 340 MiB）。四容器仍是默认与首选。
- 迁移与回滚命令、安全链、内存预设见 [operations](/operations#single-container)。

## 读路径

FreshRSS 抓取并规范化 RSS 域数据；RSSHub 只在上游生成 feed（宕机时已抓
取内容照常可读）。`FreshRSSAdapter`（Google Reader 读路径）：ClientLogin
认证、feed / entry 列表（过滤在 FreshRSS 侧执行）、entry 详情（HTML →
纯文本）、`edit-tag` 写 read/star（set 语义）。BFF 把上游协议映射为稳定
Lumi DTO；Web 只经 BFF 读写。

## 来源 / 服务控制面

- `FreshRSSControlAdapter`：subscribe / unsubscribe / 分类移动与重命名 /
  OPML 导入导出；复用读路径的同一个 `FreshRSSSession`，不向浏览器暴露
  原始凭据。
- RSSHub 控制链固定为 Browser → Lumi BFF → RSSHub；正常文章读取路径
  绝不绕过 FreshRSS 去"读 RSSHub"。预览返回的 `feedUrl` 使用
  `RSSHUB_FRESHRSS_BASE_URL`（FreshRSS 抓取视角）。
- 实例配置为 schema 驱动的类型化 allow-list：非机密键存 `lumi_settings`
  （desired/applied 两态），机密走 `SecretsStore`（write-only）；保存不
  等于生效——`restartRequired = desired ≠ applied`，operator 导出
  `rsshub.env` 片段重启 RSSHub 后调 `POST /api/v1/rsshub/config/apply`
  确认；Lumi 不自行重启 RSSHub，绝不暴露任意 shell / Docker 控制。

## AI 路径

- `AIProvider` protocol，唯一实现 `OpenAICompatibleProvider`
  （`chat/completions`，超时 connect 5s / read 60s，temperature 0.3；无
  自动重试、fallback 链、streaming）。Profile = 不同 base_url + model +
  key 组合；purpose（摘要 / 翻译 / AI 对话 / TTS）映射到具体 profile 或
  default。
- key 解析：映射的 profile 无自有 secret → `ai_not_configured`（不回退
  default/env key）；default 依次回浏览器设置的 key → env `AI_API_KEY` →
  missing。`SecretsStore` write-only，永不可回读、不入备份。
- 结果缓存于 Lumi SQLite，缓存身份 =
  `entryRef + contentHash + provider + model + promptVersion + language`；
  prompt 版本 `summary-v1` / `translation-v1` / `chat-v1`，系统提示词含
  prompt-injection 边界。
- `GET .../summary` / `GET .../translation` 只读缓存，`POST` 才显式生成；
  失败以稳定错误码返回，上游响应体不外泄。翻译仅由 AI Provider 驱动；
  本地简繁转换（OpenCC）是展示层字形转换，不属于翻译。

## 全局搜索 {#search}

FreshRSS 1.29.1 的 greader API 不提供搜索（实测 `search` 参数被忽略），
因此 Lumi 在自己的 SQLite 维护一个**派生的、100% 可重建的**搜索投影：

- 表：`search_entries`（条目文本 + read/star 镜像）、`search_feeds`
  （feed → category）、`search_meta`（同步水位）。删除全部投影表不丢失
  任何 RSS 状态；投影只服务于搜索，搜索结果的打开仍走 FreshRSS 支撑的
  entry 端点——它不是 RSS 影子库。
- 同步：BFF 后台任务按 `LUMIRSS_SEARCH_SYNC_INTERVAL`（默认 60s）增量
  同步（newest-first 翻页，"已完全见过的页"即停，增量轮有页数上限）；
  启动时投影为空 → 自动全量重建（自愈）；经 BFF 的 read/star 写入
  best-effort 镜像进投影；`POST /api/v1/search/rebuild` 手动全量重建。
- 查询语义：空白切词、最多 4 词 AND、title/正文纯文本/author 大小写
  不敏感子串匹配（参数化 LIKE，通配符转义按字面）；过滤 `state`/
  `favorite`/日期/`feedUrl`/`categoryId`；newest-first + keyset 分页
  （opaque cursor）。
- 统一搜索两条腿并列：RSS 腿 + 库腿（`search_library`：书签/剪藏/收件箱
  /Obsidian 笔记），`favorite=true` 作用于两腿；两腿独立失败——库腿异常
  时 RSS 结果照常返回，`libraryError` 如实上报。
- RAG 语义检索是可选第三条腿（sqlite-vec + fastembed，显式启用、空闲
  卸载），由 Agent 工作台与 RAG 端点消费。

## Phase-2 knowledge-workbench surface

- **Lumi library**：书签（URL 与 `rss:` 引用）、服务端剪藏（`monolith`
  服务端管线 + allow-list 清洗）、离线快照（sha256 去重 + 配额按物理
  字节计费）；统一卡片解析走 Source Registry。
- **来源接入**：API 来源（JMESPath → Atom → FreshRSS 订阅）、邮件桥
  （webhook/IMAP → 清洗 → FreshRSS 订阅 + 摘要）、收件箱推送来源
  （bearer webhook，(source, guid) 幂等）；`GET /api/v1/sources` 是
  只读统一注册表。九类来源的用户视角见 [usage](/usage#sources)。
- **RAG**：sqlite-vec + fastembed 低内存语义索引，显式启用、空闲卸载。
- **Agent 工作台**：只读工具真实执行；写工具一律 row-bound 审批记录
  （10 分钟过期），批准才执行。
- **日报与简报**：日报按配置收割搜索投影 → AI 结构化生成（严格校验，
  失败≠发布）→ upsert 期刊 → `GET /feeds/gpt-digest/{token}.atom` 只读
  输出（GET 永不触发生成）；简报 = 人工策展 + AI 起草，发布需显式确认。

## Reader 内容管线

```text
raw RSS HTML → inert DOM → controlled transforms（OpenCC 简繁、bionic、
Shiki 高亮）→ DOMPurify.sanitize（最终安全边界）→ ArticleContent
（全应用唯一 dangerouslySetInnerHTML 注入点）
```

外部链接经 `safeExternalHttpUrl` 校验（仅绝对 http/https），渲染为
`target="_blank" rel="noopener noreferrer"`。视觉/交互规则见
[design-system](/design-system)。

iOS 正文边界（`apps/ios/LumiRSS/Reader/`）——同一威胁模型的原生实现：

```text
contentHtml（不可信上游 HTML）→ controlled transforms（相对 URL 解析 +
本地排版 CSS）→ CSP meta（default-src 'none'; img-src http/https/data;
style-src 'unsafe-inline'）→ WKWebView（JS 禁用、非持久空 cookie store、
无任何 bridge；导航全部 cancel，链接点击交给受控外部打开）
```

脚本在配置层面不可执行（不是靠过滤），第三方资源加载不带 Lumi 会话
凭据（会话 cookie 只存在于 URLSession 存储）。降级路径：无 HTML 时
渲染服务端纯文本 `contentText`（转义后），明确提示而非空白。

## 前端状态

- **TanStack Query** 承载全部 server state；mutation server-confirmed 后
  invalidate，不做 optimistic update（read-later 行级乐观移除 + 行级
  错误通道是唯一例外，误差有 UI 呈现）。
- **Zustand** 承载轻量 UI 状态（`useAppSettings`、`useReaderUi`）。
  便携键经 settings-sync（600ms debounce）PATCH 到
  `/api/v1/settings`；服务端严格校验，未知键/越界/NaN 一律拒绝；多设备
  冲突可带 `baseRevision`（409 `app_settings_conflict`，Web 自动
  re-hydrate 重试一次）。

## 安全与信任边界

- **内容**：RSS/网站 HTML 视为不可信，DOMPurify 是最终边界。
- **凭据**：上游凭据只在服务端 env；AI/WebDAV/RSSHub 机密只在
  `secrets.json`（0600）；所有机密接口 write-only，不回显、不入日志/
  Git/备份；成员账号互不可见对方数据。
- **控制面**：BFF 无 Docker socket；恢复需 preview + 显式输入 `RESTORE`；
  备份归档有成员数/总量/单文件上限。
- **网络**：WebDAV http 仅允许回环/私网、重定向限同源；来源发现/预览有
  scheme/host 校验、有界 body/超时；OPML 导入上限 2 MiB；服务端取回
  URL 仅允许 http/https 并拒绝私网/环回地址（`LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS`
  显式 allow-list 除外，见 [configuration](/configuration)）。
- **边缘**：Caddy 安全响应头（nosniff / DENY / no-referrer / HSTS /
  Permissions-Policy / CSP，内联脚本 sha256 pin）；认证以应用会话为主
  （`__Host-lumirss_session`，256-bit opaque session，库里只存 SHA-256），
  basic auth 为兼容可选项；可选 BFF internal token（`X-Lumi-Token`）；
  BFF 全局请求体 4 MiB 上限与控制面路由限流（429 + `Retry-After`）。

## 故障隔离与可观测性

- RSSHub 不可用只影响来源发现/预览，不影响阅读；FreshRSS 故障以类型化
  "依赖不可用"呈现，不是空白页；
- AI 未配置/失败永不阻塞阅读、状态写入与来源管理；
- `/health/ready` 只由核心依赖（lumi.sqlite）决定；FreshRSS/RSSHub 只
  报告、永不导致 not ready；
- 备份/恢复单并发、阶段真实上报；无无界后台重试循环；日志脱敏；
  `/api/v1/operations/status` 提供各依赖真实探测。

## 明确不做（不得描述为已存在）

- Web clipping 浏览器扩展；Obsidian 自由写回（写面仅限上述受限导出
  目录，vault 读面投影永远只读）；MCP surface；
- 多租户形态 / 公共互联网硬化（邀请制多账户与可选公开注册已实现；打开
  注册后的公网暴露面由运营者自行评估）；
- PWA Push / 后台同步（app-shell 离线缓存已实现——`public/sw.js` 缓存
  静态资源与导航回退；API / 认证响应永不入缓存）；
- AI：streaming、fallback 链、多供应商自动路由。

完整非目标清单见 [roadmap](/roadmap#deferred)。

## 如何追踪实现

1. 组件事件 → `apps/web/src/api/queries.ts` 找 useXxxMutation →
   `client.ts` 找 HTTP 端点；
2. 端点 → `services/bff/src/lumirss/routers/<域>.py` → service/store →
   SQL（内联、绑定参数）或 adapter（FreshRSS 上游）；
3. 契约唯一来源：BFF Pydantic 模型 → `pnpm api:generate` 生成
   `apps/web/src/api/generated/schema.ts`。手改生成文件 = 违规（见
   [development](/development#generated-artifacts)）。

- 本页示意图解释**设计意图与边界**，不是运行时调用图；真实行为以测试
  （BFF pytest / Web vitest / e2e）与运行日志为准；
- API 家族清单以生成的 OpenAPI schema 为准（`cd services/bff && uv run
  python scripts/export_openapi.py`，Web 侧 `pnpm api:check` 有 drift 门禁）；
- FreshRSS/RSSHub 能力覆盖与委托边界逐行对照见 [upstreams](/upstreams)。
