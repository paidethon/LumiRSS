# Spec 0003 — Entry Read Path

> 日期：2026-08-27
> 对应 PRD 阶段：Phase 2 — BFF（Backend Core 续）
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**

## Goal

在 0002 已打通的 `FastAPI → FreshRSSAdapter → FreshRSS` 链路上，把
"只能读 Feed 列表"扩展成"能读文章列表 + 文章详情"：

```text
GET /api/v1/entries
    ↓
FreshRSSAdapter.list_entries()
    ↓
FreshRSS stream/contents/reading-list
    ↓
normalize（丢弃正文）
    ↓
LumiRSS Entry List JSON

选择一个 entryRef
    ↓
GET /api/v1/entries/{entryRef}
    ↓
entryRef decode → upstream item ID
    ↓
FreshRSSAdapter.get_entry()
    ↓
FreshRSS item contents
    ↓
normalize（HTML → 安全纯文本）
    ↓
LumiRSS Entry Detail JSON
```

最终真实验证：

1. `curl http://127.0.0.1:8000/api/v1/entries` 返回当前 FreshRSS 中的
   真实文章列表；
2. 从列表取一个 `entryRef`，`curl http://127.0.0.1:8000/api/v1/entries/<entryRef>`
   返回这篇文章的详细内容。

0002 回答的是 "LumiRSS 能不能通过代码使用 FreshRSS？"；
0003 回答的是 "LumiRSS 后端能不能真正阅读文章？"

**0003 是只读里程碑**：不改变 FreshRSS 中任何 Entry 状态（不标记已读、
不收藏、不调用任何 write endpoint）。

## Context — 这个阶段为什么存在（写给初学者）

### Entry 是什么？

```text
Feed  = 一个订阅源（例如 "阮一峰的网络日志"）
Entry = 这个 Feed 中的一篇文章
```

FreshRSS 负责定时抓取每个 Feed，把抓到的每篇文章存为一个 Entry。0002
读取的 subscription/list 只告诉我们"你订阅了哪些 Feed"；0003 要读的才是
Feed 里面真正的内容 —— 一篇篇具体的文章。

### Entry List 和 Entry Detail 有什么区别？

- **Entry List（文章列表）**：为"列表界面"服务。用户在列表里需要看到的
  只是：标题、来自哪个 Feed、谁写的、什么时间发布、原文链接。一屏可能
  显示 20 篇，所以每条必须**小**。
- **Entry Detail（文章详情）**：用户点开一篇文章之后使用。这时候才需要
  正文。

为什么 List 不应该把完整正文返回给未来的 React？

1. **流量与体积**：一次列表请求 20 篇文章，如果每篇都带几千字的正文，
   响应可能是几百 KB —— 而用户一篇都还没点开，99% 的内容是白传的；
2. **List 会变成正文批量下载接口**：上游 `stream/contents/reading-list`
   的响应里本来就包含正文，如果 BFF 原样透传，`GET /api/v1/entries`
   就不再是"列表接口"而是"正文打包下载器"；
3. **职责清晰**：列表接口只为列表服务，正文只从详情接口来。以后加分页、
   缓存时，两条路径可以独立演化。

因此 0003 有一个硬规则：**即使上游列表响应里已经带了正文，BFF 也必须
主动丢弃，List 响应中不出现任何正文字段。**

### entryRef 是什么？

FreshRSS（Google Reader API）给每篇文章一个上游 ID，形如：

```text
tag:google.com,2005:reader/item/00000000062d3f2b
```

为什么不把它原样放进 LumiRSS 的 URL path（`/api/v1/entries/<上面这个>`）？

1. 它包含 `/`、`,`、`:` 等字符，直接放进 URL path 会破坏路由，也
   不安全（必须转义，转义后又长又丑）；
2. 它的结构是 FreshRSS/Google Reader 的**实现细节**。如果未来 React
   直接依赖这个格式，FreshRSS 改了 ID 格式，前端也要跟着改 —— 违反
   "Adapter 隔离上游形状"的架构原则。

所以 LumiRSS 把上游 ID 包装成一个**不透明的短字符串** `entryRef`：

```text
upstream item id（UTF-8 字节）
    ↓  base64url 编码（无 padding）
    ↓  加上固定前缀
entryRef = "e1." + <base64url payload>
```

前端拿到 `entryRef` 后**只把它当不透明字符串**用：放进 URL、传回给
BFF，不解析、不猜测含义。BFF 收到后 decode 还原出 upstream item id，
再去问 FreshRSS。

**重要：编码不是加密。** Base64 只是换一种写法，任何人都能解码 —— 这
没问题，因为 entryRef 里没有秘密（item id 本身不是机密），它也完全不
是身份验证（Authorization 是另一回事）。0003 不需要签名、HMAC、
数据库映射表或 UUID —— 不过度设计。

当前仓库没有已有的 Ref 约定（0002 只有 Feed，无 Entry），因此 0003
建立这一套 `e1.` 约定，作为以后唯一的 Ref 方案，不再创建第二套。

### reading-list 是什么？

FreshRSS 的 Google Reader API 提供多个 "stream"（数据流），
`stream/contents/reading-list` 是其中之一。FreshRSS 1.29.1 源码已确认
其语义：

- **All except PRIORITY_HIDDEN**：返回全部非隐藏文章；
- 不带 `it` / `xt` filter 时 state = STATE_ALL —— 即**已读 + 未读的
  全部非隐藏 Entries**（不是"未读优先"，也没有隐含状态筛选）；
- `n` = 最大返回数量（默认 20）；`r` 默认 `d`，即 newest first。

0003 显式使用 `n=20`，不传任何 read/unread filter —— 状态筛选留给
0004。

### Mock Test 和真实 Smoke Test 的区别？（沿用 0002 的策略）

- **Mock Test**：用 `httpx.MockTransport` 在内存里伪造 FreshRSS 响应，
  测 BFF 自己的逻辑（映射、entryRef 编解码、HTML 转文本、路由、错误
  处理）。无网络、无真实密码、结果稳定。
- **真实 Smoke Test**：启动真的 BFF 连真的 FreshRSS 容器，curl 真接口，
  证明整条链路真实可用。

自动测试全用 Mock；真实验证单独做一次，不进自动测试。

## Current verified behavior（0002 已验证、0003 直接复用的事实）

以下能力**已存在且经过真实验证，0003 不得重新实现**：

- `GET /health/live`、`GET /api/v1/feeds` 两个路由可用；
- FreshRSSAdapter：ClientLogin、Auth Token 内存缓存、401 一次性重登；
- 共享 `httpx.AsyncClient`（lifespan 创建/关闭，`Timeout(10.0, connect=5.0)`，
  `trust_env=False`），Adapter 懒创建并缓存在 `app.state`；
- 4 类异常（ConfigError / AuthenticationError / UpstreamConnectionError /
  UpstreamError）及 Route 统一错误映射（`{"error": {"type": ..., "message": ...}}`）；
- 15 个自动化 Mock 测试通过；
- Secret 配置（`SecretStr` + `.env` + 空值无效）已建立。

0001 已人工验证的 FreshRSS API 事实（仅这部分）：

- ClientLogin：`POST /api/greader.php/accounts/ClientLogin`，
  表单 `Email` / `Passwd`，成功返回含 `Auth=<token>` 行；
- 所有 reader API 带 `Authorization: GoogleLogin auth=<token>` 头；
- subscription/list 已验证可用。

FreshRSS 1.29.1 源码已确认的 API 形状（Build 第 1 步 Live Probe 再对
真实运行容器确认一遍，见下文 "Build 前真实 API Probe"）：

- **List**：`GET /api/greader.php/reader/api/0/stream/contents/reading-list`
  （`n` = 最大数量，默认 20；`r` 默认 `d`，newest first）；
- **Detail**：`POST /api/greader.php/reader/api/0/stream/items/contents`，
  form body `i=<item id>`；`i` 可重复，0003 的 `get_entry()` 只发送一个。

尚未用真实容器确认的只是：真实响应字段细节与运行行为是否与源码完全
一致 —— 由 probe 完成，endpoint / method / `i` 参数形式本身不再是
未知项。

## Scope

只做四件事：

1. **entryRef 编解码**（`e1.` + base64url，纯函数，可单测）；
2. **FreshRSSAdapter 新增两个只读方法**：`list_entries()`（读
   reading-list，归一化，丢弃正文）和 `get_entry()`（按 upstream item id
   读单篇，HTML → 安全纯文本）；
3. **两个新路由**：`GET /api/v1/entries`、`GET /api/v1/entries/{entryRef}`；
4. 配套：自动化 Mock 测试（Test A–K）、一次真实 Smoke Test、文档更新
   （README / PROJECT_STATE / progress board / devlog 0003）。

外加 Build 阶段第一步：对真实 FreshRSS 做一次**只读 probe**，确认运行
容器与 1.29.1 源码结论一致，并冻结真实响应字段映射。

## Non-goals（明确不做）

Read/Unread 写入、Star/Unstar 写入、Batch state、unread/starred/feed/
category filter、public pagination（limit/cursor/page/offset 参数）、
signed cursor、search、feed add/delete、React、Web UI、SQLite、
SQLAlchemy、Alembic、RSSHub、AI、Trafilatura、原文网页抓取、
full-text extraction、HTML sanitizer framework、PWA、Caddy、ECS、
Redis、Celery、多 RSS Backend、通用 Repository / Service / Plugin /
Factory 框架。

这些属于 **0004（State / Filter / Pagination）** 或更后的里程碑，不偷偷
提前实现。

## 硬边界：0003 必须只读

`GET /api/v1/entries` 与 `GET /api/v1/entries/{entryRef}` 不得：

- 标记文章已读 / 未读；
- 收藏 / 取消收藏；
- 修改 Feed；
- 获取 write action token；
- 调用 `edit-tag`、`subscription/edit`、`token`。

**用户请求 Entry Detail 时也不得自动标记已读**（"打开后自动已读"属于
以后的专门里程碑）。自动化测试中会用 MockTransport 断言 list/detail
只触达读取相关 endpoint。

## Architecture（0003 实现范围）

冻结架构不变，0003 仍然只实现其中这一段：

```text
curl（模拟未来前端）
   ↓
FastAPI BFF（main.py，薄路由）
   ↓
FreshRSSAdapter（freshrss.py）
   ↓
FreshRSS（唯一 RSS 真源，Google Reader API）
```

```text
Feed read（0002 已有）
    ↓
Entry read（0003 新增）
```

SQLite、React、RSSHub、AI 全部不出现。

## FreshRSS API 事实（1.29.1 源码已验证）与 Build 前真实 Probe

### 源码已验证（Build 时 Live Probe 对真实容器再确认）

- **List**：`GET /api/greader.php/reader/api/0/stream/contents/reading-list?output=json`
  加 `n=20`。语义（源码确认）：All except PRIORITY_HIDDEN；无 `it` /
  `xt` filter 时 state = STATE_ALL（已读 + 未读）；`r` 默认 `d`
  （newest first）。返回 JSON 中 `items` 数组，每项可能含 `id`、
  `title`、`author`、`published`、`summary.content`、`alternate`、
  `origin.title`、`categories`，顶层可能含 `continuation`。**哪些字段
  在真实响应中存在，由 probe 确认后冻结映射。**
- **Detail**：`POST /api/greader.php/reader/api/0/stream/items/contents`，
  form body `i=<item id>`。`i` 可以重复以批量取多篇；**0003 的
  `get_entry()` 只发送一个 `i`**。

### Probe 计划（Build 第 1 步，批准后执行）

在正式写 mapping 代码之前：

1. `docker compose ps` 确认 freshrss running；
2. 用现有 BFF 开发环境（应用配置完成认证，**不读取、不打印 `.env`，
   不打印 Token / Authorization header / 密码**）做只读请求；
3. 确认**当前真实运行容器与 1.29.1 源码行为一致**（endpoint /
   method / `i` 参数形式按上文源码结论工作）；
4. 确认 List 与 Detail 的真实 Entry response fields（上面列的每个字段
   是否存在、类型），冻结字段映射；
5. 确认请求确实不修改 Entry 状态；
6. 把实际观察记录到 Spec（回填本节）和 devlog。

如果真实容器行为与源码结论不同：**暂停实现，先报告 probe 事实，等
用户确认后再修 Spec**，不自行设计替代协议。

### Probe 结果（Build 第 1 步已执行，2026-08-27，真实容器 1.29.1）

与源码结论完全一致，字段映射冻结：

- **List**（`GET .../stream/contents/reading-list?output=json&n=20`）：
  HTTP 200；顶层 keys `id` / `items` / `updated`（本次 13 条 < n=20，
  无 `continuation`）；每个 item 含 `id`（str）、`title`（str）、
  `author`（str）、`published`（int，Unix 秒）、`summary.content`（str，
  HTML）、`alternate`（`[{"href": ...}]`）、`origin`（
  `{streamId, htmlUrl, title}`）、`categories`、`canonical`、
  `crawlTimeMsec`、`timestampUsec`。
- **Detail**（`POST .../stream/items/contents`，form `i=<item id>`，单个）：
  HTTP 200；`items` 恰 1 条，结构与 List item 相同；`summary.content`
  为 HTML 正文。
- **Missing item**：fabricated id → HTTP 200 + `{"items": []}`
  （确认源码行为，EntryNotFound 映射规则成立）。
- **Read-only 证据**：detail 调用前后同一 item 的 `categories` 完全
  一致（未新增 read 状态）；probe 全程只调用了 ClientLogin /
  reading-list / items/contents 三个读取 endpoint。

## Entry List API

```text
GET /api/v1/entries
```

- 0003 不定义 `limit` / `cursor` / `page` / `offset` 等 public
  pagination parameters；客户端不得依赖这些未定义参数的行为。0004 再
  正式定义 pagination contract。
- FreshRSS 请求显式使用**固定数量参数 `n=20`**（源码已确认 `n` =
  最大返回数量，默认 20）。最多返回 20 条，防止一次拉取大量内容。
- 上游响应中的 `continuation`：0003 **不解析、不透出**。0004 处理
  pagination 时再考虑。
- 响应 envelope：

```json
{
  "items": [
    {
      "entryRef": "e1.dGFnOmdvb2dsZS5jb20sMjAwNTpyZWFkZXIvaXRlbS8wMDA",
      "title": "文章标题",
      "feedTitle": "阮一峰的网络日志",
      "author": "作者或 null",
      "url": "https://example.com/article",
      "publishedAt": "2026-08-27T12:34:56Z"
    }
  ]
}
```

返回 `{"items": [...]}` envelope 而不是裸 array：0004 可以在不破坏
`items` 的情况下增加 `nextCursor` 等字段。**但 0003 不实现也不伪造
`nextCursor`** —— 没实现的东西不假装存在。

### List 字段契约

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `entryRef` | `str`（必填） | 由 upstream item id 编码而来；没有 id 的 item 无法引用，整个跳过（不让一条坏数据炸掉整页） |
| `title` | `str`（必填） | 上游缺失时回退为 `""`，绝不让整页失败 |
| `feedTitle` | `str`（必填） | 来自 `origin.title`；缺失时回退为 `""` |
| `author` | `str \| null` | 上游缺失 → `null` |
| `url` | `str \| null` | 来自 alternate 链接；缺失 → `null` |
| `publishedAt` | `str \| null` | RFC 3339 UTC（见"时间字段"节）；缺失或明显无效 → `null`，**不伪造当前时间** |

**List 响应中禁止出现**：完整正文、`summary.content` 原始 HTML、
Auth Token、FreshRSS-specific categories 数组、read state、starred
state。即使上游已返回正文，BFF 必须主动丢弃（Test B 专门验证）。

## entryRef 方案

格式：

```text
entryRef := "e1." + base64url_bytes(utf8(upstream_item_id))   # 无 "=" padding
```

- 前缀 `e1.` 是版本标记：将来格式变化可用 `e2.`，老 ref 仍可识别；
- base64url 字符集（`A-Z a-z 0-9 - _`）URL-safe，无需转义，可安全放
  进 path；无 padding（`=` 被剥掉，解码时按需补齐）；
- 确定性：同一 upstream id 永远编码出同一 entryRef；
- 可逆：decode 后得到原始 upstream id 字符串。

### decode 校验规则（不合法一律 400，且不得触达 FreshRSS）

1. 必须以 `e1.` 开头（错误前缀如 `e2.`、`x1.`、无前缀 → 拒绝）；
2. payload 必须是非空、纯 base64url 字符集的字符串（空 payload、含
   `+` `/` `=` 或其他非法字符 → 拒绝）；
3. payload 解码后必须是合法 UTF-8；
4. 长度上限：整个 ref 超过 **512 字符**即拒绝（防止明显超长的滥用
   输入；真实 FreshRSS id 编码后远小于此）。

违反任何一条 → `InvalidEntryReference` → HTTP 400，**在 decode 阶段
就被拒绝，BFF 不会向 FreshRSS 发任何请求**（Test I 验证）。

### 实现位置

新文件 `src/lumirss/entryref.py`（约 40 行）：`encode_entry_ref()` /
`decode_entry_ref()` 两个纯函数 + `InvalidEntryReference` 异常。纯函数
无 I/O，直接单测。

## Entry Detail API

```text
GET /api/v1/entries/{entryRef}
```

流程：

```text
entryRef（URL path 参数）
    ↓ decode_entry_ref()（非法 → 400 InvalidEntryReference）
upstream FreshRSS item ID
    ↓ FreshRSSAdapter.get_entry(item_id)
FreshRSS item contents（POST stream/items/contents，form `i=<item id>`）
    ↓ normalize + HTML → contentText
Entry Detail JSON
```

响应：

```json
{
  "entryRef": "e1.dGFnOmdvb2dsZS5jb20sMjAwNTpyZWFkZXIvaXRlbS8wMDA",
  "title": "文章标题",
  "feedTitle": "Feed 名称",
  "author": null,
  "url": "https://example.com/article",
  "publishedAt": "2026-08-27T12:34:56Z",
  "contentText": "文章正文文本..."
}
```

字段规则与 List 相同（entryRef 原样返回；title/feedTitle 缺失回退
`""`；author/url/publishedAt 可为 null），另加：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `contentText` | `str`（必填） | 上游正文经 HTML→text 转换后的纯文本；上游没有正文时为 `""` |

### contentText — 为什么 0003 只返回纯文本

FreshRSS 的 `summary.content` 可能包含 HTML。RSS 内容属于**不可信
输入**（Feed 作者可以在正文里塞任意 HTML）。0003 做的是 **text-only
normalization / HTML-to-text extraction** —— 确定性的纯文本转换，
**不是完整 HTML sanitizer**（那是以后 Reader/Safe Rendering 里程碑
的事），因此不向未来 Web 暴露未经处理的 `contentHtml` —— 只提供
转换后的纯文本：

```text
HTML / markup
    ↓ deterministic text extraction（标准库）
contentText
```

转换要求（最低标准）：

- HTML tag 不出现在最终 contentText 中；
- HTML entity 正常还原（`&amp;` → `&`）；
- 基本段落不粘成一行（块级标签产生换行）；
- `<script>` / `<style>` 的**内容**被丢弃（不是留下可执行文本）；
- 输出只是一个 Python `str`，没有任何 markup。

实现：Python 标准库 `html.parser.HTMLParser` 写一个小转换器（约 40
行），放在 `adapters/freshrss.py` 内（内容归一化是 Adapter 的职责）。
**不引入** BeautifulSoup / lxml / nh3 / Trafilatura —— 标准库对本阶段
的最低要求足够，也不追求浏览器级 HTML 解析。

### 不抓取原始网页（硬边界）

如果 FreshRSS 当前 Entry 只有摘要，就返回 FreshRSS 已有的内容。
0003 **不做** `article URL → HTTP fetch → 原网页` 的全文抓取，不引入
Trafilatura / Readability / SSRF Fetcher。0003 只回答一个问题：
**FreshRSS 当前保存了什么内容？**

## 时间字段

FreshRSS Google Reader Entry 的 `published` 通常是 Unix timestamp
（秒）。LumiRSS 对外不暴露 FreshRSS 的时间格式，统一转换成：

```text
RFC 3339 UTC，如 2026-08-27T12:34:56Z
```

规则：`published` 存在且是合法数字 → 转换为 UTC RFC 3339；缺失、
非数字或明显无效（如负数）→ `null`。**绝不伪造当前时间**。

## Optional field handling（真实 RSS 很不整齐）

必须测试并保证：缺 author、缺 alternate URL、缺正文、缺 feed title、
缺 published 时，单条 Entry 仍能正常映射（nullable / 回退），**不会
导致整页 500**。唯一会导致跳过整个 item 的情况：缺 `id`（没有 id 就
无法生成 entryRef，无法被引用）。

## FreshRSSAdapter 新能力

扩展现有 `FreshRSSAdapter`（不新建任何层）：

```python
async def list_entries(self) -> list[EntryListItem]     # GET reading-list，n=20
async def get_entry(self, item_id: str) -> EntryDetail  # POST stream/items/contents，只发送一个 i
```

- 认证 / Token 缓存 / 401 一次性重登：完全复用现有 `_get_auth_token()`
  及重试模式（list_feeds 的写法直接套用）；
- 网络异常映射：沿用现有 ConnectError / ConnectTimeout / ReadTimeout →
  `UpstreamConnectionError`，5xx / 非 200 / JSON 不可解析 → `UpstreamError`；
- 不创建 EntryService / EntryRepository / FeedBackendFactory /
  DomainGateway / GenericReaderBackend 等任何新层；
- Route 保持薄：`HTTP → Adapter → Response model`。

## Response Model

新文件 `src/lumirss/models.py`（很小，一个位置放完）：

- `EntryListItem`（Pydantic）
- `EntryListResponse`（含 `items: list[EntryListItem]`）
- `EntryDetail`

Adapter 的 `list_entries()` / `get_entry()` 直接返回这些模型实例，
Route 层不再重复映射（一个定义点，无 domain/ schemas/ dto/ entities/
repositories/ 多层体系）。`main.py` 中路由直接把它们作为
`response_model` 返回。

## Error behavior

**完全复用** 0002 的四类异常与 `_ERROR_RESPONSES` 映射，不造第二套
异常框架。只新增当前真正需要的两个：

| 异常 | 定义位置 | 触发 | HTTP | error type |
| --- | --- | --- | --- | --- |
| `InvalidEntryReference` | `entryref.py` | entryRef 前缀/字符集/UTF-8/长度/空 payload 非法 | 400 | `invalid_entry_reference` |
| `EntryNotFound` | `adapters/freshrss.py` | entryRef 合法，但 FreshRSS 中找不到该 Entry | 404 | `entry_not_found` |

其余沿用 0002：`ConfigError` → 503、`AuthenticationError` /
`UpstreamConnectionError` / `UpstreamError` → 502（各自 type 不变）。

FreshRSS auth / network / upstream 错误的行为与 0002 完全一致
（包括 401 一次性重登），无新语义。

### EntryNotFound 的 Adapter 映射规则（源码已确认行为）

FreshRSS `stream/items/contents` 对不存在的 item **不返回上游 HTTP
404**，而是 HTTP 200 + `{"items": []}`。因此 `get_entry()`（只发送
一个 `i`）按返回的 items 数量映射：

- **1 个 item** → 正常，归一化为 EntryDetail；
- **0 个 item** → `raise EntryNotFound` → BFF 404；
- **>1 个 item** → `UpstreamError`（防御性处理：只请求了一个 `i`，
  正常不可能返回多个，出现即视为上游响应异常）。

## File plan

```text
services/bff/src/lumirss/
├── entryref.py            # 新增：encode/decode + InvalidEntryReference（纯函数）
├── models.py              # 新增：EntryListItem / EntryListResponse / EntryDetail
├── main.py                # 修改：+ GET /api/v1/entries、GET /api/v1/entries/{entryRef}
│                          #       + 新异常的错误映射条目
└── adapters/
    └── freshrss.py        # 修改：+ list_entries() / get_entry() / EntryNotFound
                           #         + html_to_text()（标准库 HTMLParser）
services/bff/tests/
├── test_entryref.py       # 新增：Test C + 非法 ref 各分支（纯函数，无网络）
├── test_html_to_text.py   # 新增：Test E
├── test_entry_adapter.py  # 新增：Test A / B / D / F + read-only endpoint 断言
└── test_entries_route.py  # 新增：Test G / H / I / J（注入 fake Adapter）
```

核心 implementation：

- modified existing source（2 个）：`main.py`、`adapters/freshrss.py`；
- new source（2 个）：`entryref.py`、`models.py`；
- new tests（4 个）：`test_entryref.py`、`test_html_to_text.py`、
  `test_entry_adapter.py`、`test_entries_route.py`。

不创建任何新目录、新包、新抽象层。

Milestone documentation update（完成后的文档更新，单独列出，不属核心
源码）：`README.md`、`docs/PROJECT_STATE.md`、
`docs/progress/project-data.js`、`docs/devlog/0003-entry-read-path.md`。

## Dependencies

**0 个新增第三方依赖。** 全部复用：FastAPI、HTTPX、Pydantic、
pydantic-settings、pytest（均已在 `pyproject.toml`）、Python 标准库
（`base64`、`html.parser`、`datetime`）。

如 Build 阶段发现标准库确实无法完成某项最低要求，先停下来说明原因，
未经批准不安装任何依赖。

## Testing strategy

自动测试全部：无真实网络、无真实 FreshRSS、无真实 Secret（fixture
全部使用明显是测试数据的 fake 值）。async 测试沿用 `@pytest.mark.anyio`，
route 测试沿用 `with TestClient(app)` + lifespan 启动后注入 fake
adapter（0002 已验证的模式）。

| 测试 | 验证内容 |
| --- | --- |
| **Test A — List mapping** | Fake reading-list 返回 ≥2 条 fixture → Entry List 字段正确（entryRef/title/feedTitle/author/url/publishedAt） |
| **Test B — List 不泄露正文** | Fake item 的 `summary.content` 含正文 → `/api/v1/entries` 响应序列化后不含正文任何片段 |
| **Test C — entryRef round-trip** | upstream id → encode → decode → 原 id；另测：错误前缀 / 非法 base64url 字符 / 空 payload / 超长输入 → InvalidEntryReference（纯函数测试，无网络） |
| **Test D — Detail mapping** | Fake item contents → title/feedTitle/author/url/publishedAt/contentText 全部映射正确；含 items 数量分支：0 → EntryNotFound、1 → 正常、>1 → UpstreamError |
| **Test E — HTML→text** | fixture 含 `<p>Hello &amp; LumiRSS</p><p>Second paragraph</p><script>alert(1)</script>` → 无 tags、`&` 还原、段落可读、无 `alert(1)` 可执行残留 |
| **Test F — Missing optional fields** | 缺 author / url / content / published 的 item → 仍产出契约合规响应，不 500 |
| **Test G — List route** | Fake Adapter → `GET /api/v1/entries` → 200 + `{"items":[...]}` |
| **Test H — Detail route** | Fake Adapter → `GET /api/v1/entries/{合法ref}` → 200 + EntryDetail |
| **Test I — Invalid ref** | `GET /api/v1/entries/not-a-valid-ref` → 400；且 fake Adapter 的调用计数为 0（非法 ref 不得触达 FreshRSS） |
| **Test J — Not found** | 合法 entryRef，fake Adapter 抛 `EntryNotFound` → 404 |
| **Test K — 0002 regression** | 现有 15 个测试（health / feeds / auth / token cache / error mapping）全部继续通过 |
| **补充 — Read-only 断言** | MockTransport handler 记录 list/detail 全部请求路径，断言只含读取 endpoint（无 `edit-tag` / `token` / `subscription/edit`） |

## 真实 Smoke Test（自动测试全过后执行一次）

1. `docker compose ps` 确认 freshrss running；
2. `services/bff/.env` 沿用 0002 已配置的真实凭据（Agent 不读取其内容）；
3. `cd services/bff && uv run uvicorn lumirss.main:app --port 8000`；
4. `curl http://127.0.0.1:8000/health/live` → 200 `{"status":"ok"}`；
5. `curl http://127.0.0.1:8000/api/v1/entries` → 200，真实返回文章列表；
   报告：条数、前几条标题、feed titles、entryRef 是否存在（不打印整篇正文）；
6. 从真实列表取一个 entryRef →
   `curl http://127.0.0.1:8000/api/v1/entries/<entryRef>` → 200；
   报告：title、feedTitle、publishedAt、contentText 非空及其字符数
   （**不复制整篇文章正文到报告**）。

## Acceptance Criteria

- **AC1 — Branch**：全部修改位于 `feat/0003-entry-read-path`。
- **AC2 — 0002 不回归**：`GET /health/live`、`GET /api/v1/feeds` 仍通过；
  0002 的 15 个自动化测试无 regression。
- **AC3 — Entry list**：`GET /api/v1/entries` 真实返回当前 FreshRSS
  Entries。
- **AC4 — Bounded list**：FreshRSS 请求使用固定小上限（`n=20`），不无限
  拉取。
- **AC5 — List model**：列表项至少含 entryRef / title / feedTitle /
  publishedAt，且不向客户端批量返回完整正文。
- **AC6 — entryRef**：URL-safe、opaque、deterministic、round-trip；
  非法 ref 在到达 FreshRSS 前被拒绝（400）。
- **AC7 — Entry detail**：`GET /api/v1/entries/{entryRef}` 真实返回
  对应 FreshRSS Entry。
- **AC8 — contentText**：Detail 提供安全纯文本 contentText，不提供未经
  sanitizer 处理的 contentHtml。
- **AC9 — Missing fields**：Entry 缺可选字段（author/url/content/
  published）时不导致 500。
- **AC10 — Error behavior**：invalid ref → 400；missing entry → 404；
  FreshRSS upstream errors → 复用 0002 映射。
- **AC11 — Automated tests**：新增测试 + 0002 regression 全部实际通过；
  无公网、无真实 Secret。
- **AC12 — Real smoke test**：FreshRSS → Adapter → `/entries` →
  entryRef → `/entries/{entryRef}` 完整链路真实成功。
- **AC13 — Read-only**：无 read/unread write、无 star write、无
  edit-tag、无 Feed 修改（MockTransport 断言 + 代码检查）。
- **AC14 — Scope**：未实现 pagination / filters / state writes / React /
  SQLite / RSSHub / AI / Caddy / PWA / Production / full-text fetch。

## Tasks（Build 顺序，批准后严格逐步执行）

1. Live API read-only probe（确认容器与 1.29.1 源码一致、真实响应
   字段、只读性）→ 回填 Spec / devlog；与源码结论不符则停下报告
2. entryRef encode/decode + tests（Test C）
3. `models.py`：EntryListItem / EntryListResponse / EntryDetail
4. `list_entries()` + mapping tests（Test A / B / F 的 list 部分）
5. `GET /api/v1/entries` + route tests（Test G）
6. `html_to_text()` + tests（Test E）
7. `get_entry()` + detail tests（Test D / F 的 detail 部分 + read-only
   断言）
8. `GET /api/v1/entries/{entryRef}` + 400/404 tests（Test H / I / J）
9. 全量 `uv run pytest` regression（Test K）
10. Real FreshRSS smoke test（AC12）
11. Secret / scope check（`git ls-files --cached --others
    --exclude-standard` 范围扫描，排除 gitignored `.env`，不读取其内容）
12. README / PROJECT_STATE 更新（AC 全过后才写）
13. Progress board / devlog 0003
14. 最终 `git branch` / `git status` / `git diff --stat` /
    `git diff --check` / `git diff` 检查

每完成一步立即运行对应测试，不攒到最后一次性测试。

## Verification

- `cd services/bff && uv run pytest` 全绿（0002 的 15 个 + 0003 新增，
  报告真实通过数量）；
- Smoke：`/health/live` 200 → `/api/v1/entries` 200 真实文章 →
  `/api/v1/entries/<entryRef>` 200 且 contentText 非空；
- `git status` / `git diff --stat` / `git diff --check`：无越界文件；
- secret 扫描（范围 = tracked + untracked 非 ignored，排除 `.env`）：
  无真实密码 / Token / Authorization header；
- devlog 不含整篇版权文章正文（引用只用标题、字段名、长度等元信息）。

## Risks / Unknowns

- **运行容器与源码不一致**（低概率）：endpoint / method / `i` 参数
  形式已由 FreshRSS 1.29.1 源码确认；probe 若发现运行容器行为与源码
  不符 → 停下报告，不自行发明协议。
- **reading-list 响应字段差异**：`origin.title` / `alternate` /
  `published` 等字段的真实形状由 probe 冻结；个别 Feed 缺字段由 nullable /
  回退规则兜底（Test F）。
- **HTML→text 的边界情况**：标准库 HTMLParser 不是浏览器级解析器，
  极端构造的 HTML 可能转换得不完美 —— 本阶段目标是纯文本转换
  （无 tags、无 script 内容、entity 还原、段落基本可读），不追求完美
  排版。真实 Reader 的 HTML 渲染由后续里程碑处理。

---

**本 Spec 为 Draft。在用户明确回复"批准 Spec，可以开始 Build"之前，不修改
任何仓库文件（本 Spec 自身除外）、不安装依赖、不运行初始化命令、不做
probe。**
