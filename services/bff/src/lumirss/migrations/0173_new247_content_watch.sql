-- 0173: NEW-247 原文变动关注 —— 关注记录与变化检测。
--
-- content_watches：用户对某篇文章的关注（基线正文 + sha256）。每篇
-- 至多一条关注（UNIQUE）；「检查」用提交的当前正文与基线哈希比对：
-- 相同 → watching（记 last_checked_at）；不同 → changed（存下当前
-- 正文供差异入口使用）。变化检测是显式哈希比对的事实，不是推断；
-- 差异只在「基线 vs 检测到的当前」之间计算。

CREATE TABLE IF NOT EXISTS content_watches (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL UNIQUE,
    baseline_sha256 TEXT NOT NULL,
    baseline_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'watching' CHECK (status IN ('watching', 'changed')),
    current_text TEXT,
    changed_at TEXT,
    last_checked_at TEXT,
    checks_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
