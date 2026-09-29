-- 0168: NEW-242 来源时间轴 —— 个人时间备注。
--
-- source_time_annotations：用户对某篇文章某个时间点（发表 / 接收 /
-- 更新 / 个人保存）的备注说明。时间轴本体是派生读（search_entries /
-- entry_revisions / library_bookmarks 的既有事实，查询时聚合，绝不
-- shadow-copy）；本表只存用户逐条写下的说明，一人一份，per-user 隔离。
-- 每个时间类别至多一条备注（UNIQUE 约束），更新即改写备注本身。

CREATE TABLE IF NOT EXISTS source_time_annotations (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('published', 'received', 'updated', 'saved')),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (entry_ref, kind)
);
