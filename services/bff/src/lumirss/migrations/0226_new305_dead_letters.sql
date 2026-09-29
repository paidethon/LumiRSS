-- 0231: NEW-305 接入死信处理页 —— 无法解析的 webhook 事件进入死信
-- 区。展示的是脱敏摘要（键名/类型/字节数），原始载荷只在服务端留存
-- （≤64KB，应用层截断）供修正映射后重放；API 永不回显 payload_raw。
--
-- 部分唯一索引：同一事件同时至多一条 pending 死信（重复失败更新同
-- 行）；重放成功 → status='replayed'，副作用幂等由 webhook_inbox 的
-- (endpoint_uuid, event_id) 唯一约束兜底 —— 已成功的接收不重放。

CREATE TABLE IF NOT EXISTS webhook_dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_uuid TEXT NOT NULL,
    event_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_summary TEXT NOT NULL,
    payload_raw TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    failed_at TEXT NOT NULL,
    replayed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dead_letters_pending
    ON webhook_dead_letters(endpoint_uuid, event_id) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_dead_letters_status
    ON webhook_dead_letters(status, id);
