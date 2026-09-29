-- 0167: NEW-241 文章更新差异阅读 —— 显式保存的正文版本。
--
-- article_saved_versions：用户对某篇文章显式「保存当前正文为版本」
-- 的快照（origin='manual'）。差异阅读只在用户保存过的两个版本之间
-- 进行；系统绝不自动造版本、不 shadow-copy FreshRSS 正文之外的状态
-- （正文文本由用户在阅读时显式提交保存）。
--
-- per-user 库：版本天然隔离。

CREATE TABLE IF NOT EXISTS article_saved_versions (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    label TEXT NOT NULL,
    content_text TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_article_saved_versions_entry
    ON article_saved_versions (entry_ref, created_at DESC);
