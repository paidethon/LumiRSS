-- 0244: NEW-321 Obsidian 标签映射规则 —— 源库标签 → LumiRSS 个人标签。
--
-- obsidian_tag_mappings：用户显式配置的映射规则（source → target）。
-- 只作用于导入层：投影 obsidian_notes 的标签原样保留，映射结果落在
-- obsidian_import_tags（个人标签物化层），绝不写回 Vault。
--
-- obsidian_import_tags：物化后的个人标签（note_uuid, tag）——由规则
-- 全量推导，可重复重建；Vault 文件永不被修改。

CREATE TABLE IF NOT EXISTS obsidian_tag_mappings (
    source_tag TEXT PRIMARY KEY,
    target_tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obsidian_import_tags (
    note_uuid TEXT NOT NULL,
    tag TEXT NOT NULL,
    materialized_at TEXT NOT NULL,
    PRIMARY KEY (note_uuid, tag)
);

CREATE INDEX IF NOT EXISTS idx_obsidian_import_tags_tag
    ON obsidian_import_tags (tag);
