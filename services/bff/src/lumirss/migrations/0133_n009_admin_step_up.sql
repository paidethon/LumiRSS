-- 0132: N009 管理员临时提权（step-up auth）。
--
-- 敏感管理操作（角色变更 / 暂停·恢复成员 / 配额设置 / 成员密码重置）
-- 要求短时提权令牌：POST /admin/step-up 以管理员自己的密码铸造，
-- 5 分钟有效、散列入库（token_hash，绝不存明文）、单次使用（一次
-- 消费后作废）。审计只记动作与结果，绝不记令牌或密码。

CREATE TABLE IF NOT EXISTS admin_step_up_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    operation TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_step_up_user
    ON admin_step_up_tokens (user_id, created_at DESC);
