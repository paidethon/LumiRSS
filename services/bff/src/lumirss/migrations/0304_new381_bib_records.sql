-- 0304: NEW-381 长期保存 · 书目资料记录（Zotero RDF / RIS 导入的落点）。
--
-- external_id 保留原始引用标识（Zotero item key / RIS AN、ID），
-- (source_format, external_id) 唯一 → 重复导入收敛为「对应」而不是
-- 无声复制。unsupported_fields_json 记录该条不支持字段（如实报告，
-- 不假装映射）。导入批次台账记录总数 / 新增 / 重复 / 失败与不支持字段。

CREATE TABLE IF NOT EXISTS new381_bib_records (
    id TEXT PRIMARY KEY,
    source_format TEXT NOT NULL CHECK (source_format IN ('zotero_rdf', 'ris')),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    creators_json TEXT NOT NULL DEFAULT '[]',
    pub_year TEXT NOT NULL DEFAULT '',
    publication TEXT NOT NULL DEFAULT '',
    publisher TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    abstract TEXT NOT NULL DEFAULT '',
    item_type TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    unsupported_fields_json TEXT NOT NULL DEFAULT '[]',
    import_batch_id TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_new381_bib_external
    ON new381_bib_records(source_format, external_id);
CREATE INDEX IF NOT EXISTS ix_new381_bib_created
    ON new381_bib_records(created_at);

CREATE TABLE IF NOT EXISTS new381_import_batches (
    id TEXT PRIMARY KEY,
    format TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    imported INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    unsupported_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
