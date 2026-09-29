-- 0230: NEW-304 Webhook 密钥轮换窗口 —— 管理员在受控秘密通道轮换
-- webhook 签名密钥；旧钥在短暂双钥窗口内仍可验证（不丢单），窗口
-- 过后只认新钥。秘密只存散列，明文仅在轮换响应出现一次，任何报告
-- （GET 列表/切换结果）都不回显。
--
-- webhook_key_verifications：每钥每日成功验证计数 —— 管理员据此
-- 看到切换进度（旧钥计数趋零 = 切换完成）。两张表建在 control 库
-- （迁移会同时跑在 per-user 库，属无害冗余，与 admin_step_up_tokens
-- 同口径）。

CREATE TABLE IF NOT EXISTS webhook_signing_keys (
    key_id TEXT PRIMARY KEY,
    key_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    window_ends_at TEXT
);

CREATE TABLE IF NOT EXISTS webhook_key_verifications (
    key_id TEXT NOT NULL,
    day_key TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, day_key)
);
