-- 0128 (E1): N036 刷新队列可视化 + N037 断更恢复补读。
--
-- source_refresh_log：每用户库、每来源（feed_url）的有界刷新检查记录。
--   只由两条路径写入（无任何调度器——负向契约）：
--   - F050 手动健康探测（POST /subscriptions/health-check）逐源记录；
--   - 投影增量同步（sync_incremental）对确有新交付的来源记录 ok 行。
--   result ∈ ok | stale | error：
--   - ok     = 可达且按期更新（探测 ok 且投影最新条目未超期）；
--   - stale  = 可达但久未更新（探测 ok 但投影最新条目早于阈值）；
--   - error  = 探测失败（auth/not_found/rate_limited/timeout/
--              bad_content/network_error 归并）。
--   entry_count = 该次检查对应的新交付条目数（探测路径恒 0——探测不
--   数条目，诚实于检查方式）。每源保留最近 20 条（插入时裁剪）。
--
-- feed_recovery：N037 断更恢复窗口。error/stale → ok 的跳变发生时
--   记一行：window_start = 当前连续非 ok 序列的起点（最早一条非 ok
--   的 checked_at）、window_end = 恢复时刻；entry_refs_json = 窗口内
--   该来源新交付/发布的条目引用（裸 entryRef 数组，≤50，投影查询）。
--   consumed = 0（未处理）| 1（已加入补读队列）。一次性消费：
--   to-queue 后置 1，绝不重复入队（幂等锚点）。

CREATE TABLE source_refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_url TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('ok', 'stale', 'error')),
    entry_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX ix_source_refresh_log_feed
  ON source_refresh_log(feed_url, checked_at);

CREATE TABLE feed_recovery (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    entry_refs_json TEXT NOT NULL DEFAULT '[]',
    consumed INTEGER NOT NULL DEFAULT 0 CHECK (consumed IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX ix_feed_recovery_feed
  ON feed_recovery(feed_url, created_at);
