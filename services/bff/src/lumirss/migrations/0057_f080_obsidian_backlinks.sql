-- 0057: F080 Obsidian 反链/断链 — 反向索引（投影 rescan 时重建）。
-- resolved_key：解析目标（笔记 rel_path 规范化键或标题）；broken=1 时
-- target_uuid 为空并给出 reason（unresolved / path_escaped_vault）。

CREATE TABLE obsidian_backlinks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_uuid TEXT NOT NULL,
    target_uuid TEXT,
    resolved_key TEXT NOT NULL,
    raw TEXT NOT NULL,
    alias TEXT,
    heading TEXT,
    broken INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    UNIQUE (from_uuid, resolved_key, raw)
);
CREATE INDEX idx_obs_backlinks_target ON obsidian_backlinks (target_uuid);

ALTER TABLE obsidian_notes ADD COLUMN wikilink_raws TEXT;
