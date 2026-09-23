-- 0072 / N007: 两步验证（TOTP）。
--
-- 表在控制库：TOTP 校验发生在密码登录成功之后、会话建立之前
-- （pending token 兑换会话），必须在无会话上下文里可查。
--
-- totp_settings（user_id PK）：
--   enabled              = 第二步是否启用（setup 阶段为 0）；
--   recovery_salt        = 每用户恢复码盐（hex）；恢复码只存
--                          SHA-256(salt || code) 的 JSON 数组，明文仅在
--                          enable 响应中出现一次；
--   last_used_timeslice  = 最近一次成功使用的 30 秒时间片（防重放：
--                          同一片或更早的片再次使用一律拒绝）。
-- TOTP 共享秘密不在本库——按 AD-0018-6 存每用户 secrets.json
-- （0600，键 totp_secret），数据库备份天然无此秘密。
CREATE TABLE IF NOT EXISTS totp_settings (
    user_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    recovery_salt TEXT NOT NULL DEFAULT '',
    recovery_codes TEXT NOT NULL DEFAULT '[]',
    last_used_timeslice INTEGER
);

-- 密码登录后的两步验证 pending token（不是会话）：短 TTL、一次性、
-- 只存 SHA-256(token)。兑换成功即删除；过期行在创建时顺带清理。
CREATE TABLE IF NOT EXISTS totp_pending_logins (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_totp_pending_expires
    ON totp_pending_logins(expires_at);
