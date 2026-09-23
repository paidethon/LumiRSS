-- 0071: N013 来源改名（别名）历史 —— 服务端 per-user 来源别名。
--
-- Lumi 自有元数据（feed_url 键在 per-user 库内，天然无跨账户泄漏）：
-- custom_name 是该来源的显示别名——时间线/订阅列表展示时服务端别名
-- 优先；上游（FreshRSS）标题变更绝不覆盖 custom_name（真源只读）。
--
--   source_aliases：每 feed 至多一行（PK feed_url）；删除别名只删此行。
--   source_alias_history：改名审计（旧名 + 保存时上游名快照），每 feed
--     保留最近 20 条（应用层封顶，超出删最旧）；删除别名不删历史——
--     「恢复旧名」= 用历史里的名字重新 PUT。
--
-- Web 端 localStorage 别名（R03，按 feedTitle 键）降级为离线回退：
-- 服务端有别名时服务端赢。

CREATE TABLE IF NOT EXISTS source_aliases (
    feed_url TEXT PRIMARY KEY,
    custom_name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS source_alias_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_url TEXT NOT NULL,
    old_custom_name TEXT,
    upstream_name_at_save TEXT,
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_source_alias_history_feed
    ON source_alias_history(feed_url, id DESC);
