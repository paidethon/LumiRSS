-- 0095: N071 批注原文漂移修复。
--
-- annotation_repair_log：每次自动修复（rebind）追加一行，保留旧锚点
-- JSON 与旧摘录（老引文可追溯）；应用层保留最近 10 条（cap 10），
-- 更早的历史行如实删除。原文删除后不做任何内容缓存——只有修复轨迹。

CREATE TABLE IF NOT EXISTS annotation_repair_log (
    id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL,
    old_anchor_json TEXT NOT NULL,
    old_excerpt TEXT NOT NULL DEFAULT '',
    new_block_index INTEGER NOT NULL,
    new_quote TEXT NOT NULL,
    score REAL NOT NULL,
    repaired_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_annotation_repair_log_annotation
    ON annotation_repair_log (annotation_id, repaired_at DESC);
