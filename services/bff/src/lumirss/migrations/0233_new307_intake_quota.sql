-- 0233: NEW-307 自动接入来源配额 —— 对单个 API 来源设置每天最大
-- 条目数（本地自然日）。到限后：当次只发布剩余名额，超出的条目计入
-- pending（待处理计数，不静默丢弃），用户调高上限或等次日窗口滚动。
--
-- 计数走 BEGIN IMMEDIATE 原子预占（与 ai_quota 同一原语口径），
-- 并发下绝不超额发布。

CREATE TABLE IF NOT EXISTS api_intake_quota (
    source_uuid TEXT PRIMARY KEY,
    max_items_per_day INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_intake_counts (
    source_uuid TEXT NOT NULL,
    day_key TEXT NOT NULL,
    items INTEGER NOT NULL DEFAULT 0,
    pending INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source_uuid, day_key)
);
