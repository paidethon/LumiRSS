-- 0147: NEW-205 来源保留策略启用台账 —— 预演 → 确认 → 启用。
--
-- 每行 = 一次「确认启用」的完整审计：启用时的预演快照（保留多少
-- 收藏/标注、回收多少普通缓存）+ 生效天数。策略本体仍在
-- source_overrides.retention_days（N038 单一真源）；本表只记「谁在
-- 看过哪些事实之后按了确认」，绝不替代/遮蔽策略存储。

CREATE TABLE IF NOT EXISTS new205_retention_enables (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    days INTEGER NOT NULL,
    dry_run_json TEXT NOT NULL,
    enabled_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_new205_enables_feed
    ON new205_retention_enables (feed_url, enabled_at);
