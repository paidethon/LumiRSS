-- 0268: NEW-345 共享链接使用次数上限 —— max_uses（NULL = 不限），
-- use_count 累计，exhausted_at 记录耗尽时刻；耗尽后公开路由失效，
-- 允许手动续额（topup 只加不上减），每次访问留痕（含被拒绝的访问）。

ALTER TABLE share_links ADD COLUMN max_uses INTEGER;
ALTER TABLE share_links ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE share_links ADD COLUMN exhausted_at TEXT;

CREATE TABLE IF NOT EXISTS share_link_accesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL,
    accessed_at TEXT NOT NULL,
    result TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_share_link_accesses_link
    ON share_link_accesses(link_id, id DESC);
