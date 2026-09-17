-- 0032: F11 暂时隐藏来源 / F13 新订阅阅读起点 —— 来源级显示覆盖。
--
-- Lumi 自有状态（不是 FreshRSS RSS 域数据）：抓取、订阅关系、已读/
-- 收藏全部不受影响——本表只影响「全部」时间线的显示过滤。
--   hidden_until：F11——该时间之前此来源的条目不出现在全部时间线
--     （到期自动恢复显示；NULL = 未隐藏）。
--   show_from：F13——只显示该时间之后发布的条目（历史保留不删除；
--     NULL = 无起点限制）。
-- 时间一律 UTC「Z」串（与条目 published_at 比较同形）。

CREATE TABLE IF NOT EXISTS source_overrides (
    feed_url TEXT PRIMARY KEY,
    hidden_until TEXT,
    show_from TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
