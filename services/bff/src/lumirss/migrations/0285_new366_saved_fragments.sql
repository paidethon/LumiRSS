-- 0285: NEW-366 段落级搜索结果 —— 用户从长文命中段落中保存的片段。
--
-- 只保存用户显式选择的段落文本（≤400 字/条），绝不自动保存整篇；
-- entry_ref 关联本人投影（per-user 库：A 的片段对 B 不可见）。
-- query 记录保存时的查询（回看「当时为什么保存」），不做外键约束
-- （投影可重建，片段按 entry_ref 打开时经既有解析路径）。

CREATE TABLE IF NOT EXISTS search_saved_fragments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_ref TEXT NOT NULL,
    entry_title TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    paragraph_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_saved_fragments_entry
    ON search_saved_fragments (entry_ref, id DESC);
