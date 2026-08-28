# Spec 0004 — Entry State + Filter + Cursor Pagination

> 日期：2026-08-28
> 对应 PRD 阶段：Phase 2 — BFF（Backend Core 收官）
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**

## Goal

在 0003 的只读 Entry 路径上，补齐一个真正 RSS Reader 后端最重要的三类
能力，完成 Phase 2 Backend Core：

```text
① State（状态写入）        read / unread，star / unstar
② Filter（筛选）           all / unread / starred / by feed
③ Pagination（分页）       FreshRSS continuation → LumiRSS opaque cursor
```

最终后端支持：

```text
GET /api/v1/entries
GET /api/v1/entries?view=unread
GET /api/v1/entries?view=starred
GET /api/v1/entries?feedUrl=...
GET /api/v1/entries?view=unread&feedUrl=...
GET /api/v1/entries?cursor=...

PATCH /api/v1/entries/{entryRef}/state
```

0002 回答"LumiRSS 能不能通过代码使用 FreshRSS？"，0003 回答"能不能
真正阅读文章？"，0004 回答"**能不能像一个 RSS Reader 一样：筛选、翻页、
标记已读、收藏？**"

完成后：LumiRSS Backend Core 足以支撑第一版 React Reader（0005 起）。

## Context — 这个阶段为什么存在（写给初学者）

### State 是什么？

```text
read    = 这篇文章是否已读
starred = 这篇文章是否收藏
```

FreshRSS 仍然是这两个状态的**唯一真源**。LumiRSS 不把 read/starred
复制到 SQLite，也不在 BFF 里另记一份 —— 状态只存在 FreshRSS，LumiRSS
每次都实时读写它。这样客户端和服务器永远不会出现"两本账"。

为什么不在读取文章时顺手标记已读？那是以后专门里程碑的决定（比如
Reader 打开时才触发）。0004 只提供**显式的状态写入 API**。

### Filter 是什么？

```text
all      = 全部文章（已读 + 未读）
unread   = 只看未读
starred  = 只看收藏
feed     = 只看某一个订阅源的文章
```

关键原则：**不是 LumiRSS 自己下载所有文章再用 Python filter**。

错误做法：

```text
FreshRSS 拉 20 篇 all
    ↓
Python 里过滤 unread
    ↓
可能只剩 3 篇（还少给了 17 篇的配额）
```

正确做法：把 filter 翻译成 FreshRSS 自己的 filter 语言，让 FreshRSS
在数据库里筛选，返回的 20 篇全部都是用户要的：

```text
FastAPI view=unread
    ↓
FreshRSSAdapter 翻译
    ↓
FreshRSS it=user/-/state/com.google/unread
    ↓
返回 20 篇 unread
```

Feed 筛选同理（访问 FreshRSS 的 feed 专属 stream，而不是拉全量再筛）。

### Pagination 是什么？为什么需要？

不能一次返回几千篇 Entry：

1. **响应体积**：几千篇的 JSON 是几 MB 级别，移动端流量和内存都受不了；
2. **没人看得完**：用户一屏只看 20 篇，其余全是白传；
3. **上游有边界**：FreshRSS 的 stream 接口本来就按 `n` 分批给。

所以要"翻页"：

```text
第一页（20 篇）
    ↓ nextCursor
第二页（20 篇）
    ↓ nextCursor
……
    ↓ nextCursor = null（没有更多了）
```

### FreshRSS continuation 是什么？

FreshRSS 上游分页机制：stream 响应里带一个
`"continuation": "123456"`，下一页请求带上 `c=123456`，FreshRSS 就从
那之后继续给。**这是 FreshRSS 的私有协议细节。**

LumiRSS 对外的分页参数叫 `cursor`。continuation 和 cursor **不是同一个
公共 Contract** —— 如果未来 React 直接依赖 continuation 格式，FreshRSS
改版前端就得跟着改，违反"Adapter 隔离上游形状"原则。所以 0004 引入
Cursor Envelope（见下文）。

### Auth Token 和 Action Token 有什么区别？

两种 Token，两条获取链，都必须视为 Secret：

```text
API Password ──ClientLogin──→ Auth Token        （身份：我是谁）
Auth Token   ──GET /token───→ Action Token      （写操作凭证：允许修改）
```

- **Auth Token**（0002 已有）：每次 API 调用的身份凭证，放在
  `Authorization: GoogleLogin auth=...` 头里。
- **Action Token**（0004 新增）：FreshRSS 对**修改操作**
  （`edit-tag` 写状态）要求的额外 POST 参数 `T=<action token>`。

FreshRSS 源码里有兼容捷径（`T=""` 或 `T=x` 可能被某些版本接受），
**LumiRSS 严禁依赖** —— 始终走 `GET /token` 拿真实 Action Token。

### Set State 和 Toggle 有什么区别？

API 设计成**目标状态**（set）而不是**翻转**（toggle）：

```text
read=true   → 确保已读
read=false  → 确保未读
starred=true / false 同理
```

为什么不用 toggle？考虑网络请求超时后重试：

```text
SET true → 超时 → 重试 SET true   结果：已读（正确且一致）
toggle   → 超时 → 重试 toggle     结果：如果第一次其实成功了，
                                   两次 toggle 回到未读（错误！）
```

SET 语义让 API **幂等（idempotent）**：同样的请求发一次和发 N 次，
结果完全相同。客户端可以放心重试。

### Cursor 不是安全令牌

```text
Base64url ≠ encryption（编码不是加密，任何人都能解码）
Cursor   ≠ authentication（cursor 不证明身份）
Cursor   ≠ authorization（cursor 不授权访问任何东西）
```

Cursor 只是 LumiRSS 对 FreshRSS continuation 的**版本化、可校验的
包装**。0004 不需要 HMAC / signature / JWT / 数据库 cursor 表 /
Redis —— 不过度设计。

## Current verified behavior（0002/0003 已验证，0004 直接复用）

以下能力已存在且经过真实验证，0004 **不得重新实现**：

- `GET /health/live`、`GET /api/v1/feeds`、`GET /api/v1/entries`、
  `GET /api/v1/entries/{entryRef}` 四个路由可用；
- FreshRSSAdapter：ClientLogin、Auth Token 内存缓存、读路径 401
  一次性重登（清 token → 重登 → 重试一次，无循环）；
- 共享 `httpx.AsyncClient`（lifespan 创建/关闭），Adapter 懒创建缓存在
  `app.state`；
- 6 类异常（ConfigError / AuthenticationError / UpstreamConnectionError /
  UpstreamError / InvalidEntryReference / EntryNotFound）及
  `_ERROR_RESPONSES` 统一映射；
- entryRef（`e1.` + base64url，round-trip，非法 ref 在触达 FreshRSS 前
  400）；
- reading-list 响应字段形状已由 0003 probe 冻结（items 内含
  `id` / `title` / `author` / `published` / `summary.content` /
  `alternate` / `origin` / `categories`，顶层含 `continuation` 可能存在）；
- 58 个自动化 Mock 测试全部通过。

0004 只在以上基础上**扩展**，不新建层、不重构。

## Scope

只做四件事：

1. **读取模型加状态**：EntryListItem / EntryDetail 增加 `read` /
   `starred` bool 字段（来自 FreshRSS 真实状态）；
2. **GET /api/v1/entries 扩展 query**：`view`（all/unread/starred）+
   `feedUrl` + `cursor`，全部由 FreshRSS 上游筛选（无 Python post-filter）；
3. **Cursor pagination**：`cursor` / `nextCursor` 公共契约 +
   `c1.` Cursor Envelope 编解码与校验；
4. **PATCH /api/v1/entries/{entryRef}/state**：set 语义的
   read/starred 写入（Action Token + edit-tag，单篇，一次性 401 恢复）。

外加 Build 阶段第一步：对真实 FreshRSS 1.29.1 做只读 probe + 可恢复
write probe，确认 filter / continuation / state marker / token /
edit-tag 实际行为，冻结 mapping。

### 与 PROJECT_STATE 描述的差异说明（Category 为 deferred）

`docs/PROJECT_STATE.md` 的 Next milestone 一节写了 "category filters"，
但 0004 **不实现 Category**（本次任务指令明确排除）。处理方式：收尾
更新 PROJECT_STATE 时，把 Category 筛选**明确记录为 deferred / later
milestone**（若 PRD 仍要求，归入后续里程碑），而不是简单删除 ——
不假装从未计划过。0004 只做 all/unread/starred/feed 四种筛选。

## Non-goals（明确不做）

React / Web UI、Category 管理与筛选、Feed add/delete、OPML、
**Mark all as read**（FreshRSS API 支持也不顺手做）、**批量已读 /
批量收藏**（0004 只操作单篇 Entry）、Search、Full-text fetch /
Trafilatura、SQLite、AI、RSSHub、Caddy、PWA、Alibaba ECS、Offline
cache、Redis、Celery、multi-user、OAuth、generic repository/service
framework、multi RSS backend。

## 硬边界

冻结架构不变：

```text
React（未来）
    ↓
FastAPI BFF
    ↓
FreshRSSAdapter
    ↓
FreshRSS
```

- read / starred 状态由 FreshRSS 保存，**禁止** `FastAPI → SQLite →
  read/starred`；
- SQLite 仍然只保留未来的 AI / cache / settings，0004 不引入 SQLite；
- 所有 read / starred / continuation 不持久化：Cursor 是
  request/response only，Token 是 memory only，State 真源是 FreshRSS；
- 不做 BFF 内 post-filter（Test C/D + 源码检查验证）；
- Adapter 理解 FreshRSS continuation，BFF 理解 LumiRSS cursor ——
  Adapter 不负责 HTTP public cursor semantics。

## FreshRSS API 事实（任务已核验，Build 时 Live Probe 再确认）

以下来自任务指令中对固定版本 FreshRSS 1.29.1 的核验，Build 第一步对
真实容器 probe 确认后冻结：

### Read filtering

```text
it=user/-/state/com.google/unread      → 只返回 unread
```

### Starred filtering

```text
it=user/-/state/com.google/starred     → 只返回 starred
```

### Page size

`n=<integer>` = 最大返回数量。0004 继续固定 `n=20`，不暴露 public
`limit` / `pageSize` / `perPage` / `offset` / `page`（避免同时维护
offset 和 cursor 两套分页逻辑）。

### Continuation

响应：

```json
{ "items": [...], "continuation": "123456" }
```

下一页请求 `c=123456`。0004 必须真正使用这个机制。

### Feed scoped stream

Feed 专属文章流的 stream id 是 `feed/<feedUrl>`，作为 path 一部分访问
（概念上 `stream/contents/feed%2F<encoded feedUrl>`）。**Adapter 必须正确
URL encode 上游 feed stream path**（`/` 和 `:` 等字符都要转义）；真实
encoding 行为由 probe 确认后冻结。

### State markers（读取）— FreshRSS 1.29.1 源码已验证

固定 mapping（**源码已验证**；Live Probe 只确认实际容器行为一致，
**不再用于决定 mapping**）：

```text
"user/-/state/com.google/read" in categories
    → read = true；否则 read = false

"user/-/state/com.google/starred" in categories
    → starred = true；否则 starred = false
```

`categories` 缺失时 read/starred 均为 false，不得 500。

### State writes（写入）

```text
POST /reader/api/0/edit-tag
```

form 参数：

```text
T=<action token>          必需（不用 T="" / T=x 兼容捷径）
i=<item id>               必需
a=user/-/state/com.google/read       增加状态
r=user/-/state/com.google/read       移除状态
a/r 同理用于 starred；a / r 可重复出现
```

一次请求可同时改 read + starred（repeated form params），**不拆成两个
网络请求**，除非真实 probe 证明必须拆。

### Action Token

```text
GET /reader/api/0/token
```

携带现有 `Authorization: GoogleLogin auth=<Auth Token>` 头，返回
Action Token。**严禁依赖 FreshRSS 对 `T=""` / `T=x` 的兼容行为**。

## Probe 计划（Build 第 1 步，批准后执行）

分两类。全程不读取、不打印 `.env` / Token / Authorization header /
密码 / 文章正文。

### Read-only probe

确认当前真实容器与上述结论一致：

```text
it=unread                 只返回未读
it=starred                只返回 starred
n=20                      边界
c=<continuation>          翻页
feed scoped stream        URL encode 后真实可达
read/starred markers 与固定 mapping 一致（mapping 已由源码验证冻结）
```

### Write probe（可恢复，必须有 cleanup）

只选**一个已有 Entry**，先读取并记录 `original_read` /
`original_starred`（只记 bool，不记正文）：

```text
读取原状态
    ↓
只反转一个状态（如 read = !original_read）
    ↓
读取验证状态真实改变
    ↓
恢复原状态
    ↓
再次读取确认恢复成功
```

恢复失败 → **立即停止并明确报告，不得继续其它 Build 步骤**。
starred 验证遵循同样原则（禁止永久取消用户已有收藏）。

如果 probe 发现真实行为与任务结论不符（尤其 feed URL path encoding）：
**暂停实现，先报告 probe 事实，等用户确认后再修 Spec**，不偷偷改
Public API。

### Probe 结果（Build 第 1 步已执行，2026-08-28，真实容器 1.29.1）

全部与源码结论一致，映射冻结：

- **it=unread**：HTTP 200，12 items，全部 unread（all_unread=True）；
- **it=starred**：HTTP 200，0 items（当前无收藏，空集 all_starred=True）；
- **feed scoped stream**：`stream/contents/feed/<quote(url, safe="")>`
  → HTTP 200，10 items，全部属于目标 Feed（same_feed=True）；源码确认
  regex 允许 `%` 字符并 urldecode 后查库；
- **continuation**：当前数据 13 条 < 20，无 continuation —— 如实记录
  "Real continuation unavailable because current dataset has <= 20
  entries"，pagination 语义由自动 Mock 测试覆盖；
- **state markers**：当前页面 1/13 read、0/13 starred，与固定 mapping
  一致；
- **GET /token**：HTTP 200，返回有效 Action Token（长度 57，实现不
  硬编码该长度）；
- **edit-tag**：单字段写入（flip read）与组合写入（restore read +
  flip starred，一个请求携带 T/i/r/a 四个字段）均返回 HTTP 200 +
  body `"OK"`，状态真实改变；
- **Cleanup**：write probe 结束后 read/starred 均恢复原状
  （False/False == 原状），通过 stream/items/contents 再次读取确认；
- **实现层发现**：httpx 0.28.1 AsyncClient **不接受 list-of-tuples
  作为 `data`**（被当作 sync stream → RuntimeError）；生成重复 form
  字段的正确最小方式是 `urllib.parse.urlencode(list_of_pairs)` +
  `content=` 传参（同时显式设置 `Content-Type:
  application/x-www-form-urlencoded`）。

## Public API Contract

### GET /api/v1/entries — query 参数

| 参数 | 类型 | 规则 |
| --- | --- | --- |
| `view` | `str \| None`（未提供 = None） | 枚举 `all` / `unread` / `starred`；非法值 → FastAPI/Pydantic 422；不支持组合（如 unread+starred 双状态复合过滤），`view` 只能取一个枚举值。**Route 层必须区分"view 未提供"与"显式 view=all"**（cursor 场景下二者行为不同，见 Cursor scope 解析规则；实现上即参数声明为 Optional，`None` = 未提供，`"all"` = 显式） |
| `feedUrl` | `str \| None` | 未提供 → None；来自 `GET /api/v1/feeds` 的 normalized `feedUrl`；不创建 feedRef / feed ID database / feed mapping table（feed URL 本身就是稳定身份，单用户 MVP 足够） |
| `cursor` | `str \| None` | LumiRSS opaque cursor（见下文），非法 / scope mismatch → 400 |

等价关系（仅无 cursor 时成立）：`GET /api/v1/entries` ≡
`GET /api/v1/entries?view=all`。有 cursor 时，"view 未提供"会采用
cursor 的 scope，而"显式 view=all"要求 cursor scope 必须就是 all
—— 二者语义不同，见下文 Cursor scope 解析规则。

view → FreshRSS 翻译（Adapter 职责）：

```text
view=all      → reading-list，无 it filter（0003 现状）
view=unread   → it=user/-/state/com.google/unread
view=starred  → it=user/-/state/com.google/starred
```

feedUrl + view 组合合法（表达"某个 Feed 的全部/未读/收藏文章"）：
Feed scope + state filter 一起交给 FreshRSS 的**同一个请求**，不先拉
全量再 Python filter。

### 响应 envelope

```json
{
  "items": [
    {
      "entryRef": "e1....",
      "title": "Article",
      "feedTitle": "Example",
      "author": null,
      "url": "https://example.com",
      "publishedAt": "2026-08-28T00:00:00Z",
      "read": false,
      "starred": true
    }
  ],
  "nextCursor": "c1...."
}
```

- 没有下一页：`"nextCursor": null`（不伪造、不省略字段）；
- 0003 已有的 items 字段规则全部不变（title/feedTitle 缺失回退 `""`，
  author/url/publishedAt nullable，List 仍然绝不返回正文）。

### entryRef / Detail 不变 + 状态字段

- entryRef 方案（`e1.` + base64url）完全不变；
- `GET /api/v1/entries/{entryRef}` 响应同样增加 `read` / `starred`
  bool 字段；其余字段（含 contentText 规则）不变。

为什么 List 和 Detail 都带状态？未来 React Article List 直接知道
未读样式 / 收藏图标，不需要为每一篇额外请求一次状态。

## Cursor 设计

### 格式（Cursor Envelope）

```text
cursor := "c1." + base64url(utf-8 compact JSON)   # 无 "=" padding
```

payload 概念：

```json
{"c": "123456", "v": "unread", "f": "https://example.com/feed.xml"}
```

| 字段 | 含义 |
| --- | --- |
| `c` | FreshRSS continuation（非空数字字符串） |
| `v` | 产生该 cursor 时的 view（`all` / `unread` / `starred`） |
| `f` | 产生该 cursor 时的 feedUrl，或 `null` |

encode 流程：dict → `json.dumps`（compact separators，key 顺序确定）
→ UTF-8 → base64url → 去掉 `=` padding → 前缀 `c1.`。

前缀 `c1.` 是版本标记（将来格式变化用 `c2.`），与 `e1.` 同一风格。

### Cursor scope 解析规则（view / feedUrl 的权威解析）

**无 cursor 的请求：**

```text
view 未提供   → 按 all 处理
feedUrl 未提供 → None
```

**有 cursor 的请求：**

```text
decode cursor，恢复 continuation + view + feedUrl
    ↓
request 未显式提供 view / feedUrl
    → 直接使用 cursor 中的 scope（cursor 独立可请求下一页）
request 显式提供了 view / feedUrl
    → 必须与 cursor scope 完全相同；不同 → 400 invalid_cursor
```

因此：

```text
GET /api/v1/entries?cursor=<cursor>
```

**必须可以独立请求下一页**，不需要重复携带 view / feedUrl。

为什么 scope 校验只在"显式提供"时进行？为了避免 continuation 与
filter scope 混用：第一页 `view=unread` 得到 cursor A（属于 unread
流），用户却拿 cursor A 请求 `view=starred` —— continuation 和 filter
属于两个不同的流，数据会错乱。因此显式提供的 view / feedUrl 与
cursor scope 不一致时：

```text
400 invalid_cursor，且不向 FreshRSS 发任何请求
```

Route 层必须能够区分：

```text
"view 未提供"（None）   → cursor 场景下采用 cursor scope
"显式 view=all"（"all"） → cursor 场景下要求 cursor.v == "all"
```

### validation 规则（非法一律 400 invalid_cursor，不触达 FreshRSS）

1. 前缀必须 `c1.`；
2. payload 非空、纯 base64url 字符集；
3. base64url 解码后是合法 UTF-8；
4. 是合法 JSON object；
5. schema 合法：恰好 `c` / `v` / `f` 三个 key，`c` 为非空数字字符串，
   `v` ∈ {all, unread, starred}，`f` 为 string 或 null；
6. 总长度上限 **2048 字符**。

### 实现位置

新文件 `src/lumirss/cursor.py`（纯函数）：
`encode_cursor(continuation, view, feed_url)` /
`decode_cursor(cursor)` + `InvalidCursor` 异常 + 一个
`verify_cursor_scope(...)` 校验函数（或 decode 返回结构体后由路由层
比对，实现时取最简方式）。

### Cursor / State 均不持久化

Cursor request/response only，Token memory only，State 真源 FreshRSS。
不新增 SQLite。

## FreshRSSAdapter 新能力

扩展现有 `FreshRSSAdapter`（不新建任何层）：

```python
async def list_entries(
    self,
    *,
    view: EntryView = EntryView.ALL,        # 或等价 Literal/str 约定
    feed_url: str | None = None,
    continuation: str | None = None,
) -> EntryPage
```

- `EntryPage`：概念上 `{items: list[EntryListItem], upstream_continuation:
  str | None}`（定义在 `models.py`，Adapter 直接返回，路由层再转
  nextCursor）；
- **Adapter 返回 upstream continuation，不理解 LumiRSS cursor**；
  BFF / 路由层负责 `upstreamContinuation ↔ nextCursor` 转换与 scope
  校验；
- feed 流：`feed_url` → stream id `feed/<feed_url>` → 正确 URL encode
  进 path；
- view → `it` 参数翻译；continuation → `c` 参数；
- read/starred markers 从 `categories` 解析（`_common_fields()` 扩展）；
- 401 一次性重登模式完全复用现有写法。

### State write

```python
async def set_entry_state(
    self,
    item_id: str,
    *,
    read: bool | None = None,
    starred: bool | None = None,
) -> None
```

（命名可依实现微调，但语义固定：set，不是 toggle。）

映射规则：

```text
{"read": true}    → a=user/-/state/com.google/read
{"read": false}   → r=user/-/state/com.google/read
{"starred": true} → a=user/-/state/com.google/starred
{"starred": false}→ r=user/-/state/com.google/starred
同时修改两个状态  → 一个 edit-tag 请求携带多个 a=/r= 参数
```

## Action Token 生命周期与安全

Adapter 增加 `_action_token`（进程内存）：

```text
第一次写操作
    ↓ 没有 action token
    ↓ 用现有 Auth Token GET /reader/api/0/token
    ↓ 保存到 Adapter instance memory
    ↓ POST edit-tag
之后复用 _action_token
```

`GET /token` 返回值验证（FreshRSS 1.29.1 为兼容旧客户端会接受
`T=""` / `T=x`；LumiRSS 已明确禁止依赖该兼容捷径，因此把可疑值当作
上游异常处理）：

```text
response text 必须 strip
    ↓
strip 后为空 → UpstreamError
值为 "x"    → UpstreamError
    ↓
不缓存、不继续 edit-tag
```

不硬编码 Action Token 长度（如 57 字符）—— 避免与 FreshRSS 内部实现
产生不必要的耦合。

安全规则：

- Action Token **只存在 Adapter process memory**；
- 不得：写文件、写 SQLite、写 .env、写日志、返回浏览器、写 devlog、
  写测试快照（真实值）；
- 与 Auth Token 一样属于 Secret，最终 secret 扫描范围覆盖它。

### Auth Token 变化时必须同步失效 Action Token

现有读路径 401 恢复会执行 `self._auth_token = None`；**任何**清除
`_auth_token` 的地方必须同步清除 `_action_token`（二者都与当前
FreshRSS credential 状态相关，避免"新 Auth Token + 旧 Action Token"
混用）。

### Write 401 一次性恢复

`edit-tag` 返回 401（可能 Auth 或 Action Token 失效）：

```text
清除 _auth_token + _action_token
    ↓ 重新 ClientLogin
    ↓ 重新 GET /token
    ↓ 重试 edit-tag 恰好一次
```

再次失败 → `AuthenticationError`。禁止无限 retry。

## PATCH State API

```text
PATCH /api/v1/entries/{entryRef}/state
```

JSON body 规则：**至少一个字段具有真正的 bool 值**。

有效：

```json
{"read": true}
{"read": false}
{"starred": true}
{"starred": false}
{"read": true, "starred": false}
```

无效（均返回 422，用 FastAPI/Pydantic 当前最小验证方式实现等价客户端
错误，不造复杂 error framework）：

```json
{}
{"read": null}
{"starred": null}
{"read": null, "starred": null}
```

即：某字段为 `null` / 省略表示"不修改该状态"，但必须存在**另一个
有效 bool 字段**，否则整个请求 422 —— 在到达 Adapter / FreshRSS 之前
就被拒绝。

- `read` / `starred` 使用**严格 bool**（或当前 Pydantic 下的最小等价
  方式）：不把 `1` / `0` / `"true"` 等隐式转换成 bool；
- entryRef 非法 → 400 `invalid_entry_reference`，且 `GET /token` 与
  `edit-tag` 均不得被调用；
- **格式合法但实际不存在的 Entry**：FreshRSS 1.29.1 的 edit-tag
  **不保证**对不存在 item 返回 404，它可能仍返回 OK。0004 不为此增加
  pre-read existence lookup，也不为该 edge case 增加一次额外 GET。
  语义明确为：

  ```text
  invalid entryRef format → 400
  FreshRSS 接受 edit-tag  → 204
  ```

  204 表示**写请求被 FreshRSS 接受**，不额外承诺再次确认 Entry 存在。
  正常客户端只能使用 `GET /entries` 返回的 entryRef；
- **set 语义**：`read=true` → ensure read；`read=false` → ensure
  unread；严禁 toggle API；
- 成功 → **204 No Content**（不为返回完整 Entry 多调一次 FreshRSS；
  未来 React 收到 204 后更新本地 TanStack Query cache，真实状态验证由
  重新 GET Entry 完成）。

## Error behavior

复用现有异常与 `_ERROR_RESPONSES` 映射，只新增一个：

| 异常 | 定义位置 | 触发 | HTTP | error type |
| --- | --- | --- | --- | --- |
| `InvalidCursor` | `cursor.py` | cursor 前缀/字符集/UTF-8/JSON/schema/长度非法，或 scope 与当前 view/feedUrl 不匹配 | 400 | `invalid_cursor` |

其余沿用：`InvalidEntryReference` → 400、`EntryNotFound` → 404、
空 PATCH body → FastAPI/Pydantic 422、FreshRSS auth/network/upstream →
现有映射。不建第二套错误框架。

## File plan

```text
services/bff/src/lumirss/
├── models.py            # 修改：EntryListItem/EntryDetail + read/starred；
│                        #       EntryPage（items + upstreamContinuation）
├── cursor.py            # 新增：encode/decode/scope 校验 + InvalidCursor
├── main.py              # 修改：GET /entries query 参数 + cursor 转换 +
│                        #       PATCH state 路由 + InvalidCursor 映射
└── adapters/
    └── freshrss.py      # 修改：view/feed/continuation 翻译、state markers
                          #       解析、_action_token、edit-tag、write 401
                          #       恢复、_auth_token 失效同步清 action token

services/bff/tests/
├── test_cursor.py            # 新增：Test G（round-trip + 非法分支）
├── test_entry_filters.py     # 新增：Test A/B/C/D（state mapping、view、
│                             #       feed、combined，MockTransport 断言
│                             #       上游参数与无 post-filter）
├── test_entry_state.py       # 新增：Test I/J/K/L/M/N/O/P（action token、
│                             #       edit-tag 映射、401 恢复）
└── test_entries_pagination.py# 新增：Test E/F/H/Q + query 路由测试
```

- modified existing source（3 个）：`models.py`、`main.py`、
  `adapters/freshrss.py`；
- new source（1 个）：`cursor.py`；
- new tests（4 个）：如上（推荐划分，Build 时可按实际最小合并调整）。

不创建 `repositories/` / `services/` / `state_manager/` /
`pagination_service/` / `command_bus/` 等任何新层。

Milestone documentation update（AC 全过后单独做）：`README.md`、
`docs/PROJECT_STATE.md`、`docs/progress/project-data.js`、
`docs/devlog/0004-entry-state-filter-pagination.md`。

## Dependencies

**0 个新增第三方依赖。** 复用 FastAPI、HTTPX、Pydantic、
pydantic-settings、pytest 及 Python 标准库（cursor 只用 `json` +
`base64`）。如确需新增依赖，Spec/Build 中先说明原因，未经批准不安装。

## Testing strategy

自动测试全部：无公网、无真实 FreshRSS、无真实 Secret、不读真实
`.env`（fixture 全用明显 fake 值，如 `fake-action-token-0004`）。
沿用 `@pytest.mark.anyio` + MockTransport + TestClient 注入 fake
adapter 模式。

| 测试 | 验证内容 |
| --- | --- |
| **Test A — State mapping** | Fake item categories 含 read/starred marker → bool 正确；categories 缺失 → `False/False` 不 500 |
| **Test B — view mapping** | view=all → 无 it；view=unread → `it=...unread`；view=starred → `it=...starred`（断言上游请求参数） |
| **Test C — feed filter** | feedUrl 正确编码进 FreshRSS feed stream path；无 Python post-filter |
| **Test D — combined filter** | feedUrl + view=unread → 同一上游请求同时含 feed scope + unread filter |
| **Test E — continuation mapping** | Fake 第一页带 `continuation` → nextCursor 非空；第二页 cursor decode → `c=12345` 真实传给 Adapter/FreshRSS |
| **Test F — no continuation** | 上游无 continuation → `"nextCursor": null` |
| **Test G — cursor round-trip** | continuation + view + feedUrl → encode → decode → 完全相同；bad prefix / bad base64 / bad JSON / wrong schema / invalid continuation / too long 全部 `InvalidCursor` |
| **Test H — cursor scope** | ① 仅携带 cursor、无 view/feedUrl → 直接采用 cursor scope 独立取下一页成功；② cursor scope 与**显式提供的** view（或 feedUrl）不一致 → 400 且断言没触达 FreshRSS（fake adapter 调用数为 0） |
| **Test I — action token** | Fake `GET /token` 返回 `fake-action-token-0004` → 缓存到 Adapter memory；第二次 write 不重复获取。`/token` 返回 200 + empty / 200 + whitespace / 200 + `"x"` → `UpstreamError`，不缓存，且 edit-tag 从未被调用 |
| **Test J — mark read** | `{"read": true}` → POST edit-tag：`i=<id>` + `a=com.google/read` + `T=<fake action token>` |
| **Test K — mark unread** | `{"read": false}` → `r=com.google/read` |
| **Test L — star / unstar** | starred=true → add starred；starred=false → remove starred |
| **Test M — combined state PATCH** | `{"read": true, "starred": false}` → 恰好一个 edit-tag 请求，含正确的 repeated form params |
| **Test N — invalid PATCH body** | `{}` / `{"read": null}` / `{"starred": null}` / `{"read": null, "starred": null}` → 422；不调用 FreshRSS（不调 `/token`、不调 edit-tag） |
| **Test O — invalid entryRef** | 非法 ref → 400；`GET /token` 与 `edit-tag` 均未被调用 |
| **Test P — write 401 recovery** | 第一次 edit-tag 401 → 清两个 token → ClientLogin → GET token → 恰好重试一次；第二次失败 → `AuthenticationError`，无循环 |
| **Test Q — state route** | Fake Adapter 成功 → 204 |
| **Test R — regression** | 0002 + 0003 全部现有测试继续通过 |

不追求固定测试数量；数量由行为自然决定，最终只报告真实 `XX passed`。

## 真实 Smoke Test（自动测试全过后执行一次）

前提：`docker compose ps` 确认 freshrss running；`services/bff/.env`
沿用现有真实凭据（Agent 不读取其内容）。

### Read smoke

```text
GET /api/v1/entries
GET /api/v1/entries?view=unread
GET /api/v1/entries?view=starred
GET /api/v1/entries?feedUrl=<real feed>
```

报告：HTTP status、entry count、few sample titles（不复制正文）。

### Pagination smoke

第一页 → 若 `nextCursor != null` → `GET /api/v1/entries?cursor=<nextCursor>`
→ 验证第二页 200、无第一页最后一条重复、cursor 可继续。报告只写
"cursor present / cursor page request succeeded"，不打印 cursor decode
内容。若当前数据 ≤ 20 条无法产生 continuation：如实报告
"Real continuation unavailable because current dataset has <= 20 entries"，
不伪造通过（自动测试仍完整覆盖 pagination）。

### Filter scope smoke

真实验证 cursor scope mismatch 被拒绝（如 view=unread 的 cursor 用于
view=starred 请求 → 400）。

### State smoke（可恢复，cleanup 是验收标准）

选一个真实 Entry：

```text
GET Detail → 记录 read / starred（只记 bool）
PATCH read = opposite → 204
GET Detail → 状态真实改变
PATCH read = original → 204
GET Detail → 状态恢复
starred 同样执行一遍（先记录 → 临时反转 → 验证 → 恢复 → 确认）
```

最终必须：`read == 测试前 && starred == 测试前`，否则 **AC FAIL 并立即
报告**，不得把"测试成功但忘了恢复"算 PASS。

## Acceptance Criteria

- **AC1 — Branch**：全部修改位于 `feat/0004-entry-state-filter-pagination`。
- **AC2 — Regression**：0002 + 0003（health / feeds / entry list /
  entry detail）全部旧测试继续通过。
- **AC3 — State fields**：Entry List / Detail 的 `read` / `starred`
  来自 FreshRSS 真实状态。
- **AC4 — View filters**：all / unread / starred 实际由 FreshRSS 筛选。
- **AC5 — Feed filter**：`feedUrl` 真实过滤到指定 Feed。
- **AC6 — Combined filter**：view + feedUrl 组合真实生效。
- **AC7 — Cursor**：Public API 使用 cursor / nextCursor，不直接暴露
  raw FreshRSS continuation。
- **AC8 — Pagination**：第一页 continuation 正确产生 nextCursor；下一页
  cursor 正确转换回 upstream continuation。
- **AC9 — Cursor validation**：非法或 scope mismatch cursor → 400 且
  不触达 FreshRSS。
- **AC10 — Action Token**：写状态前 GET /token 并安全内存缓存；不使用
  `T=x` / `T=""` 兼容捷径。
- **AC11 — Read state**：真实验证 read true / false 均同步到 FreshRSS。
- **AC12 — Starred state**：真实验证 starred true / false 均同步。
- **AC13 — Set semantics**：API 是 set desired state，不是 toggle。
- **AC14 — PATCH contract**：至少一个字段；成功 204。
- **AC15 — Retry**：Write 401 → 清 auth + action token → re-auth →
  新 action token → 恰好重试一次；无无限 retry。
- **AC16 — Smoke cleanup**：真实 state test 后 read/starred 恢复原状。
- **AC17 — Automated tests**：全部新增 + regression 实际通过；无真实
  网络 / Secret。
- **AC18 — Secret safety**：无 Password / Auth Token / Action Token /
  Authorization Header / .env 泄漏到待提交内容（扫描范围 = tracked +
  untracked 非 ignored，排除 gitignored `.env`，Agent 不读取 `.env`）。
- **AC19 — Scope**：未实现 React / Category 管理 / Batch writes /
  Mark all read / Feed CRUD / SQLite / RSSHub / AI / Caddy / PWA /
  Production。
- **AC20 — Backend Core milestone**：完成后可明确标记 Phase 2 Backend
  Core 完成；**不开始 0005**。

## Tasks（Build 顺序，批准后严格逐步执行，每步完成立即跑对应测试）

1. Live API probe（read-only：it=unread / it=starred / n=20 / c= /
   feed scoped stream / state markers；write：单 Entry 可恢复探测
   /token + edit-tag）→ 回填 Spec / devlog；与结论不符则停下报告
2. Live Probe 确认真实容器 read/starred markers 与固定 mapping 一致
   （mapping 已由 1.29.1 源码验证冻结，probe 仅确认，不重新决定）
3. `cursor.py` encode/decode/scope 校验 + Test G
4. `models.py`：EntryListItem/EntryDetail + read/starred；EntryPage
5. Adapter view filters（it 翻译）+ Test B（+Test A）
6. Adapter feedUrl filter（stream path encoding）+ Test C / D
7. continuation + cursor 集成（EntryPage → nextCursor）+ Test E / F / H
8. `GET /entries` query 路由 + 路由测试（scope mismatch 400 不触达
   FreshRSS）
9. Adapter Action Token 获取/缓存 + Test I
10. Adapter edit-tag state mapping（单/组合）+ Test J / K / L / M
11. `PATCH /state` 路由（204、空 body 422、非法 ref 400 不触达）+
    Test N / O / Q
12. Write 401 一次性恢复 + auth/action token 同步失效 + Test P
13. 全量 `uv run pytest` regression（Test R）
14. Real filter smoke（view/feedUrl 真实生效）
15. Real pagination smoke（可恢复、如实报告）
16. Reversible state smoke + restore（AC11/12/16，cleanup 是验收标准）
17. Secret / scope check（tracked + untracked 非 ignored 扫描）
18. README / PROJECT_STATE / progress board / devlog 0004 更新
19. 最终 `git branch` / `git status` / `git diff --stat` /
    `git diff --check` / `git diff` 检查；**停在等待 Review**

## Verification

- `cd services/bff && uv run pytest` 全绿（报告真实数量）；
- 真实 smoke：filters / pagination / state（含恢复）如上各节；
- `git status` / `git diff`：无越界文件；
- secret 扫描零命中（含 Action Token）；
- devlog 不含真实 Token / 密码 / Authorization header / 完整正文。

## Risks / Unknowns

- **feed stream path encoding**：`feed/<url>` 的真实 encoding 行为由
  probe 冻结；不符则停下报告，不偷改 Public API。
- **state markers**：mapping 已由 FreshRSS 1.29.1 源码验证并冻结
  （read / starred in categories）；Live Probe 仅确认实际容器一致。
  若 probe 发现不一致（如版本升级 / 魔改）→ 停下报告，不自行改
  mapping。categories 缺失容错为 false/false。
- **真实数据 < 20 条**：无法产生真实 continuation → 如实报告，靠自动
  测试覆盖 pagination 语义。
- **edit-tag 响应形状**：成功响应的真实形状由 write probe 确认后冻结；
  非 200 / 异常走现有 UpstreamError 映射。

---

**本 Spec 为 Draft。在用户明确回复"批准 Spec，可以开始 Build"之前，不修改
任何仓库文件（本 Spec 自身除外）、不安装依赖、不运行初始化命令、不做
probe。**
