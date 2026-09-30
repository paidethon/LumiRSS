-- 0315: NEW-392 通知聚合规则 —— 用户自选的「同来源/同类型合并」偏好。
--
-- 规则只改变**展示**（分组摘要），不改变数据：每个原始事件仍完整
-- 存在（0314），摘要展开就是逐条事件列表。规则按 (user_id, kind,
-- source) 唯一——同一来源同类型至多一条，禁用后回到平铺视图。

CREATE TABLE IF NOT EXISTS notification_aggregation_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notif_agg_rules_unique
    ON notification_aggregation_rules(user_id, kind, source);
