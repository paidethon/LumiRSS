-- 0308: NEW-385 WARC 档案索引导入。
--
-- 逐记录资源索引（URI / 记录类型 / 大小 / 摘要 / HTTP 状态）+ 批次
-- 台账（跳过 / 超限 / 活动内容计数）。正文只有用户显式选择且记录为
-- 安全文本类型时才存（body_text，有单条与总量上限）；HTML/脚本一律
-- 只索引不落正文（无活动内容入库）。

CREATE TABLE IF NOT EXISTS new385_warc_records (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    target_uri TEXT NOT NULL,
    record_type TEXT NOT NULL DEFAULT '',
    record_id TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    content_length INTEGER NOT NULL DEFAULT 0,
    payload_digest TEXT NOT NULL DEFAULT '',
    warc_date TEXT NOT NULL DEFAULT '',
    http_status TEXT NOT NULL DEFAULT '',
    active_content INTEGER NOT NULL DEFAULT 0,
    body_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_new385_warc_batch
    ON new385_warc_records(batch_id, created_at);

CREATE TABLE IF NOT EXISTS new385_warc_batches (
    id TEXT PRIMARY KEY,
    record_count INTEGER NOT NULL DEFAULT 0,
    imported INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    oversized_count INTEGER NOT NULL DEFAULT 0,
    active_content_count INTEGER NOT NULL DEFAULT 0,
    body_imported_count INTEGER NOT NULL DEFAULT 0,
    notes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
