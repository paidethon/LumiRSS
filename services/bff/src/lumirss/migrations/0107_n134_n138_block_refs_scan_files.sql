-- 0107: N134 块级回跳（block refs）+ N138 文件级同步诊断（最近一次扫描）。
--
-- N134：obsidian_block_refs —— 投影扫描时从笔记正文提取 ^lumi-<paraId>
-- 块 id（Obsidian 官方块 id 语法；导出批注在 handoff markdown 中内嵌的
-- 回跳锚点），支撑「哪些笔记引用了这个段落」的反查（round-trip）。
-- 数据完全派生自 obsidian_notes.body_text，rescan 时全量重建，与反链
-- 索引（0057）同一策略：可随时删除重建，不承载独立事实。
CREATE TABLE obsidian_block_refs (
    para_id TEXT NOT NULL,
    note_uuid TEXT NOT NULL REFERENCES obsidian_notes(item_uuid) ON DELETE CASCADE,
    indexed_at TEXT NOT NULL,
    PRIMARY KEY (para_id, note_uuid)
);

CREATE INDEX ix_obsidian_block_refs_note ON obsidian_block_refs(note_uuid);

-- N138：最近一次扫描的文件级诊断（只保留最后一次，重扫即覆盖）。
-- JSON 结构（服务端每类列表截断到 50 条 + truncated 标志，诚实截断）：
-- {"added": {"items": [...], "truncated": false}, "changed": {...},
--  "removed": {...}, "skipped": {...}}
ALTER TABLE obsidian_settings ADD COLUMN last_scan_files_json TEXT NOT NULL DEFAULT '';
