-- 0241: NEW-315 书签链接批量替换 —— 旧域 → 新域的明确映射，先预览
-- 每项变化，执行后本批可撤销。
--
-- 批次行记录 from_domain/to_domain + 每一项的 before/after（changes_json
-- 是撤销的真源）；书签行只在新域替换后无同 URL 冲突时更新（唯一索引
-- 冲突项如实列入 conflicts，绝不静默丢弃）。原始 URL 在 undo 前不保留
-- 在书签上——撤销完全依赖批次台账回放。per-user。

CREATE TABLE IF NOT EXISTS bookmark_link_replacements (
    id TEXT PRIMARY KEY,
    from_domain TEXT NOT NULL,
    to_domain TEXT NOT NULL,
    changed INTEGER NOT NULL,
    conflicts INTEGER NOT NULL,
    changes_json TEXT NOT NULL,
    undone_at TEXT,
    created_at TEXT NOT NULL
);
