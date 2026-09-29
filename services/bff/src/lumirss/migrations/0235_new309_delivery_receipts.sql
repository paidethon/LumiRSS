-- 0235: NEW-309 Webhook 投递回执 —— 逐次投递尝试的状态、重试计划
-- 与脱敏响应（状态码 + 文本摘要，≤300 字符，控制字符剥离；请求头与
-- 签名永不回显）。
--
-- idempotency_key 对同一 (subscription, event) 家族的每次尝试保持
-- 一致 —— 手动重试用同一幂等标识，接收端可安全去重。

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_uuid TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    response_status INTEGER,
    response_excerpt TEXT,
    next_retry_at TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_sub
    ON webhook_deliveries(subscription_id, id);
