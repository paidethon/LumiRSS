-- 0234: NEW-308 外发 Webhook 事件订阅 —— 用户选择本人数据的少量
-- 事件类型发送到已验证的 HTTPS 地址。
--
-- state: pending（创建，未验证）→ active（verify 通过）→ paused
-- （用户暂停）→ revoked（撤销，终态；回执保留）。签名秘密存
-- per-user 秘密文件（SecretsStore，0600，库外），表里只有散列与
-- 状态 —— 与「秘密不进 lumi.sqlite 备份」的 AD-0018-6 同口径。

CREATE TABLE IF NOT EXISTS webhook_out_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    target_url TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    verify_token_hash TEXT,
    created_at TEXT NOT NULL,
    verified_at TEXT,
    UNIQUE(event_type, target_url)
);
