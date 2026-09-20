-- 0050: F056 跨设备继续阅读 + F058 批注复习队列。
--
-- reading_progress：entry_ref 主键 upsert（同条目最新 updated_at 胜出，
-- 服务器时间是唯一仲裁）；device_label ≤32 字符（应用层限额）。
--
-- review_queue：批注复习排期（annotation_id UNIQUE；批注删除级联删除
-- 由应用层执行——SQLite 无指向外部的 FK）。

CREATE TABLE IF NOT EXISTS reading_progress (
    entry_ref TEXT PRIMARY KEY,
    para_id TEXT NOT NULL,
    pct REAL NOT NULL DEFAULT 0,
    device_label TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL UNIQUE,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'due' CHECK (status IN ('due', 'done')),
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
