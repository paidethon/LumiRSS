-- 0040: F021 手工关联内容 —— 用户手工建立的条目间关联（无 AI 参与）。
--
-- src_ref/dst_ref 是 ItemRef（rss:<entryRef> / library:<uuid>）；
-- UNIQUE(src_ref, dst_ref) 支撑幂等创建与 409 冲突语义。关系是 Lumi
-- 自有元数据：目标内容被删除（RSS 条目失效）时关系保留，读取时按
-- registry 解析标记 stale，从不自动删除。

CREATE TABLE IF NOT EXISTS item_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_ref TEXT NOT NULL,
    dst_ref TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (src_ref, dst_ref)
);

CREATE INDEX IF NOT EXISTS idx_item_relations_src ON item_relations (src_ref);
CREATE INDEX IF NOT EXISTS idx_item_relations_dst ON item_relations (dst_ref);
