-- 0045: F033 快照资源诊断 + F034 快照版本。
--
-- resources：JSON 数组 [{url, status: ok|failed|skipped, error?}]，
-- 有界 ≤200 条（超出标记 truncated）；versions：每快照最多 5 版 FIFO，
-- 存 sha256 + 净化后纯文本（旧版可查看文本，不保留原始 HTML 文件）。

ALTER TABLE library_assets ADD COLUMN resources TEXT;
ALTER TABLE library_assets ADD COLUMN resources_truncated INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS snapshot_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_uuid TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshot_versions_lookup
    ON snapshot_versions (snapshot_uuid, id);
