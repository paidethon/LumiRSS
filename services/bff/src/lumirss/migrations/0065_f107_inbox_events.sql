-- 0065: W6 Inbox（F107 投递详情与失败重放）。
-- 每次投递（成功/重复/失败）一条事件；payload_json 为重放所需的最小
-- 原始载荷（有界）；payload_hash 参与去重依据展示。写入侧裁剪总量。
CREATE TABLE inbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uuid TEXT NOT NULL,
    guid TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('delivered', 'duplicate', 'failed')),
    error_summary TEXT,
    payload_hash TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX inbox_events_source ON inbox_events (source_uuid, id DESC);
