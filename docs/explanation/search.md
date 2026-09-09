# How Global Search Works

> 机制解释。API 与配置键细节：`GET /api/v1/search`、`POST
> /api/v1/search/rebuild`；`LUMIRSS_SEARCH_SYNC_INTERVAL`（默认 60 秒，
> `0` 关闭后台同步）见 [../reference/configuration.md](../reference/configuration.md)。

## 为什么需要投影

FreshRSS 1.29.1 的 greader API 不提供搜索（实测：`search` 参数在
`stream/contents` 与 `stream/items/ids` 上都被忽略）。因此 Lumi 在自己的
SQLite 中维护一个从 FreshRSS 条目构建的搜索投影。

## 投影的性质

- 表：`search_entries`（条目文本 + read/star 镜像）、`search_feeds`
  （feed → category，支持单参数分类过滤）、`search_meta`（同步水位），
  由 migration 0006 建立。
- **派生、100% 可重建**：删除全部投影表不丢失任何 RSS 状态；每一行都能
  从 FreshRSS 重新同步。它**不是** RSS 域的影子数据库——投影只服务于
  搜索，不为任何其他目的创建、更新或读取条目；搜索结果的打开仍走正常的
  FreshRSS 支撑的 entry 端点。
- 查询用参数化 LIKE（SQL 侧转义）而非 FTS5：单用户规模下全扫毫秒级，
  子串语义对 CJK 与拉丁文一致，1-2 字短查询无需 trigram 回退。

## 同步机制

- BFF 内后台任务按 `LUMIRSS_SEARCH_SYNC_INTERVAL`（默认 60s）增量同步：
  按 newest-first 翻页拉取 FreshRSS 条目，"已完全见过的页"即停止；
  增量轮有页数上限（有界工作量）。
- 启动时投影为空 → 自动全量重建（自愈）；同步失败记录日志、下轮重试，
  永不阻塞阅读路径。
- **镜像写入**：经 BFF 的条目 read/star 状态写入会 best-effort 同步进
  投影；FreshRSS 侧的直接改动由下一轮同步收敛。
- 显式 `POST /api/v1/search/rebuild` 可手动触发有界全量重建（管理员操作）。

## 查询语义

- 查询串按空白切词，**最多 4 个词**，全部词都要命中（AND）；
- 每个词在 title / 正文纯文本 / author 三列做**大小写不敏感子串匹配**
  （引号是普通字符，无短语语法）；
- 通配符（`%`、`_`、`\`）在绑定期转义，按字面匹配——用户输入不会被
  解释为 LIKE 模式；
- 过滤参数：`state=unread`、`favorite`（starred）、`from`/`to`
  （ISO 日期，含/排他）、`feedUrl` 或 `categoryId`（互斥）限定范围；
- 排序 newest-first，分页为 `(published_at, item_id)` keyset，包在
  opaque 的 `q1.` cursor 信封里；
- snippet 从净化后的正文纯文本提取，Web 端按纯文本渲染，绝不进 HTML 路径。
