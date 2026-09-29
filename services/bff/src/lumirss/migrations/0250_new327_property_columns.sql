-- 0250: NEW-327 笔记属性列映射 —— frontmatter 字段 → 列表可见列（可筛选）。
--
-- properties_json：扫描投影时提取的有界 frontmatter 属性（键/值字符串化，
-- ≤20 键 × ≤200 字符）。纯派生、随 rescan 重建；绝不回写用户文件，
-- 原文件格式保持不变。既有行回填 '{}'（下次扫描后如实填充）。
--
-- obsidian_property_columns：用户指定的列映射（字段名 → 展示名/可见/
-- 可筛选/排序位）。字段不必预先存在——投影里没有该字段时列如实为空。

ALTER TABLE obsidian_notes ADD COLUMN properties_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS obsidian_property_columns (
    field TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    visible INTEGER NOT NULL DEFAULT 1,
    filterable INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
