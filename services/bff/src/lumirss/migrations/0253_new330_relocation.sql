-- 0253: NEW-330 资料路径重定位向导 —— 源目录移动后指向新根，按
-- content-hash 匹配原条目，避免全部重复导入。
--
-- 预览（previewed）产出 relocated/fresh/changed/vanished/ambiguous/
-- collision 六类清单（json 有界）；apply 只做两件事：把匹配到的档案
-- 行 rel_path 改到新布局（行 id 不变 = 不重复导入），并把档案根切到
-- 新路径。匹配键 = parse_note 的 content_hash（sha256 原始字节，与
-- FIX-337/339 改名侦测同口径）；同哈希多候选一律进 ambiguous，绝不瞎猜。

CREATE TABLE IF NOT EXISTS obsidian_root_relocations (
    id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES obsidian_root_profiles(id) ON DELETE CASCADE,
    new_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('previewed', 'applied')),
    relocated_json TEXT NOT NULL DEFAULT '[]',
    fresh_json TEXT NOT NULL DEFAULT '[]',
    changed_json TEXT NOT NULL DEFAULT '[]',
    vanished_json TEXT NOT NULL DEFAULT '[]',
    ambiguous_json TEXT NOT NULL DEFAULT '[]',
    collision_json TEXT NOT NULL DEFAULT '[]',
    applied_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obsidian_root_relocations_root
    ON obsidian_root_relocations (root_id, created_at DESC);
