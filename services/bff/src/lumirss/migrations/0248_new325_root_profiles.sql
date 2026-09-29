-- 0248: NEW-325 资料库多根目录档案 —— 每个授权资料根一个独立只读档案。
--
-- obsidian_root_profiles：授权根的档案行（路径、忽略规则、授权状态、
-- 最近一次扫描状态）。路径经 canonical_vault_root 校验（containment
-- 同主 Vault 口径）；扫描只读，绝不写根目录。
--
-- obsidian_root_notes：各根独立的笔记档案（与主投影 obsidian_notes
-- 解耦，互不复制）；content_hash 与主投影同一口径（sha256 原始字节，
-- FIX-337/339 改名侦测同款），是 NEW-330 重定位匹配的键。

CREATE TABLE IF NOT EXISTS obsidian_root_profiles (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    root_path TEXT NOT NULL,
    ignore_globs_json TEXT NOT NULL DEFAULT '[]',
    authorized INTEGER NOT NULL DEFAULT 1,
    last_scan_at TEXT,
    last_error TEXT,
    last_report_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obsidian_root_notes (
    id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES obsidian_root_profiles(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    indexed_at TEXT NOT NULL,
    UNIQUE (root_id, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_obsidian_root_notes_hash
    ON obsidian_root_notes (root_id, content_hash);
