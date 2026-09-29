-- 0229: NEW-303 Webhook 接收收件箱 —— 已授权端点接收的条目先进
-- 待确认区（pending），用户审阅后 accept（纳入）/ reject（拒绝）。
--
-- webhook_endpoints：接收端点注册表（per-user）；bearer 秘密走
-- control 库 token_owner_index（machine_auth），不落本表。
-- webhook_inbox：(endpoint_uuid, event_id) 唯一 —— 幂等接收，同
-- 事件重放收敛为 duplicate；已裁决条目永不被重放覆盖。

CREATE TABLE IF NOT EXISTS webhook_endpoints (
    uuid TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_uuid TEXT NOT NULL,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    received_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(endpoint_uuid, event_id)
);

CREATE INDEX IF NOT EXISTS idx_webhook_inbox_status
    ON webhook_inbox(endpoint_uuid, status, id);
