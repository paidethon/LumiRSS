-- 0145: NEW-202 订阅停更观察 —— per-feed 观察期状态。
--
-- 每用户库。同一来源同时至多一条 active 观察（部分唯一索引）；
-- 到期后由用户在复核表面选择「继续观察 / 停订」，系统只提供事实
-- （最后成功检查 / 实际发文变化 / 抓取健康），绝不自动停订。
--
-- status ∈ active | closed；closed 行保留 resolution（continue|
-- unsubscribed）作决定台账。ends_at 是「到期复核日」，无调度器：
-- 到期 = 查询时如实标注 expired，等用户复核。

CREATE TABLE IF NOT EXISTS new202_observations (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    note TEXT,
    started_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    resolution TEXT CHECK (resolution IN ('continue', 'unsubscribed')),
    closed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_new202_active_per_feed
    ON new202_observations (feed_url) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_new202_observations_feed
    ON new202_observations (feed_url, started_at);
