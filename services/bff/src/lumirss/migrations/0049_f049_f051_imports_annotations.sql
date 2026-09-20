-- 0049: F049 导入批次追踪 + F051 批注服务端化。
--
-- import_batches：OPML/书签/MD 笔记导入的可追溯批次（counts 如实、
-- errors ≤50 条、retry_payload ≤50 条失败项；幂等重试的依据）。
--
-- annotations：批注从 localStorage 迁到服务端真源（Web 端 localStorage
-- 降级为离线缓存）。anchor_hash UNIQUE 承载导入幂等（同一锚点重复
-- 导入不产生第二行）。excerpt ≤500、note ≤2000（应用层限额）。

CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('opml', 'bookmarks', 'md_notes')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    counts_json TEXT NOT NULL DEFAULT '{}',
    errors_json TEXT NOT NULL DEFAULT '[]',
    retry_payload_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    anchor_json TEXT NOT NULL,
    anchor_hash TEXT NOT NULL UNIQUE,
    excerpt TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT 'yellow',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_annotations_entry ON annotations (entry_ref);
