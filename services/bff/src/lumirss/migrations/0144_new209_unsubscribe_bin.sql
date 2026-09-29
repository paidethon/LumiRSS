-- 0144: NEW-209 订阅变动回收箱 —— 退订时捕获订阅配置，限期可恢复。
--
-- 每用户库。捕获发生在退订成功**之后**（上游清单已无此订阅）：
-- feed_url / stream_id / title / category 全套配置留在箱内；keep_days
-- 由用户选择，purge_after = unsubscribed_at + keep_days 只是「建议清
-- 理日」（本库无调度器——过期行如实标注 expired，等待显式 discard，
-- 与全库「无后台清理器」口径一致）。
--
-- status ∈ kept | restored | discarded：
-- - kept      箱内可恢复；
-- - restored  已按原配置重新订阅（restored_stream_id = 新代次 stream
--   id；同一 URL 重新订阅是新代次，上游已删正文不承诺恢复）；
-- - discarded 用户显式放弃（行保留作审计）。

CREATE TABLE IF NOT EXISTS new209_unsubscribe_bin (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    title TEXT,
    category_id TEXT,
    category_label TEXT,
    keep_days INTEGER NOT NULL,
    unsubscribed_at TEXT NOT NULL,
    purge_after TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'kept' CHECK (status IN ('kept', 'restored', 'discarded')),
    restored_at TEXT,
    restored_stream_id TEXT,
    discarded_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_new209_bin_feed
    ON new209_unsubscribe_bin (feed_url, unsubscribed_at);
