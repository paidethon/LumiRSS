-- 0142: NEW-210 来源抓取停机计划 —— per-feed 暂停区间（可取消）。
--
-- 每用户库：行只属于创建它的用户，无需 user 列。一个来源可有多条
-- 计划（历史保留）；「生效中」谓词 = status='active' 且 start_at <= now
-- 且（end_at IS NULL 或 now < end_at）。取消是 set 语义（active →
-- cancelled），行永不删除（审计友好；无调度器清后台——与全库口径
-- 一致：purge 是显式未来项，不在本表实现）。
--
-- 诚实边界（与 source_freshness 同一口径）：FreshRSS 的抓取调度粒度
-- 由实例 CRON_MIN 决定，greader API 不提供 per-feed 暂停。本计划在
-- Lumi 侧的可消费面：/new210/pauses/active 机器可读端点 + 本组表面
-- （NEW-202 观察列表 / NEW-206 日历）对暂停来源如实标注。绝不伪装
-- 成「已停止 FreshRSS 抓取」。

CREATE TABLE IF NOT EXISTS new210_pause_plans (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    reason TEXT,
    start_at TEXT NOT NULL,
    end_at TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    cancelled_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_new210_pause_plans_feed
    ON new210_pause_plans (feed_url, start_at);
