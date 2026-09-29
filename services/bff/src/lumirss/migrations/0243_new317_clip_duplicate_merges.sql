-- 0243: NEW-317 剪藏重复合并 —— 同页多次剪藏（URL 变体：追踪参数/
-- scheme/尾斜杠）保留版本与选段，用户选择合并元数据或保持分开。
--
-- 合并 = 把被并入剪藏的「选区包」（NEW-312，clip_item_uuid 重指向）
-- 与「修订版本」（revised_*，保留侧缺失时才迁移）并入保留剪藏，然后
-- 被并入侧走 F019 软删（回收站可恢复原始行）。meta_policy 记录用户
-- 对元数据的选择（kept=保留侧标题；newest=最新剪藏标题）；合并台账
-- 只追加，绝不静默改写。原始 content_html 永不互相覆盖。per-user。

CREATE TABLE IF NOT EXISTS clip_duplicate_merges (
    id TEXT PRIMARY KEY,
    kept_item_uuid TEXT NOT NULL,
    merged_item_uuids_json TEXT NOT NULL,
    meta_policy TEXT NOT NULL CHECK (meta_policy IN ('kept', 'newest')),
    carried_selections INTEGER NOT NULL DEFAULT 0,
    carried_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clip_merges_kept
    ON clip_duplicate_merges (kept_item_uuid, created_at DESC);
