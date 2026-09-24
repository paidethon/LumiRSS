-- 0088: N041 今日必读队列 + N042 队列分段 + N043 队列冻结快照。
--
-- reading_queue：每用户库一行一个「今日队列成员」。entry_ref 存统一
-- ItemRef（``rss:<entryRef>``，与 workspace_items.item_ref 同构——
-- 引用而非复制，解析在读取时经 Source Registry 完成，ADR 0004）；
-- queue_date 是服务端 UTC 日期（YYYY-MM-DD），跨设备共享同一个「今天」。
--   source:  manual（手动加入）| budget（按预算生成）| level（预留：
--            N020 关注级别在本仓库尚未实现，生成端当前绝不写入）；
--   status:  pending | done（完成，按条目身份记账，set 语义）|
--            removed（显式移除；行保留——同日同条目幂等复活/防重入
--            的锚点，也保证「生成绝不复活被手动移除的条目」）；
--   segment: N042 可选分段标签（NULL = 未分组）。段的成员关系完全由
--            行派生（与 N101 workspace_items.group_name 同一取舍），
--            不建段表——「组内最后一条被移走后孤儿行」的 GC 问题由
--            派生语义天然消解。
--
-- reading_queue_meta：每队列日一行的呈现元数据（segment_order_json =
-- 段名有序数组，与 workspaces.group_order_json 同构的呈现顺序提示；
-- 行在首次设置时创建，无需预播种）。
--
-- queue_snapshots：N043 冻结快照。payload_json 只携带 ItemRef + 顺序
-- 元数据（{items:[{item_ref, position, segment}], segment_order}），
-- 绝不复制内容；快照不可变——冻结后新加入的项绝不进入旧快照，消失
-- 的 ref 由读取侧诚实呈现占位（绝不复活）。
--
-- 队列日无外键锚点（队列行不级联于任何实体）；条目删除/退订后行仍
-- 存在，读取侧以解析失败呈现占位（N043 契约对活队列同样成立）。

CREATE TABLE reading_queue (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    added_at TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    queue_date TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'budget', 'level')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'removed')),
    segment TEXT
);

CREATE UNIQUE INDEX ux_reading_queue_day_ref
  ON reading_queue(queue_date, entry_ref);

CREATE INDEX ix_reading_queue_order
  ON reading_queue(queue_date, position);

CREATE TABLE reading_queue_meta (
    queue_date TEXT PRIMARY KEY,
    segment_order_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE queue_snapshots (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    queue_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX ix_queue_snapshots_date
  ON queue_snapshots(queue_date, created_at);
