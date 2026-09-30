-- 0307: NEW-384 JSON Feed 个人导出台账。
--
-- 台账记录导出范围（clips / bib）、条数、包含字段清单与授权范围
-- 说明文本（原样进响应）。Feed 本体即时返回，不落库。

CREATE TABLE IF NOT EXISTS new384_feed_exports (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    clip_count INTEGER NOT NULL DEFAULT 0,
    bib_count INTEGER NOT NULL DEFAULT 0,
    fields_json TEXT NOT NULL DEFAULT '[]',
    authorization_scope TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
