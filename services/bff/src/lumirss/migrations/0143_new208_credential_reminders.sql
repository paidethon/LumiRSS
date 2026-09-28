-- 0143: NEW-208 来源认证到期提醒 —— 凭据到期日的提醒元数据。
--
-- 只存「提醒」：到期日 + 备注（≤200 字符）+ 续期计数。schema 里
-- 没有、也绝不允许出现凭据正文（没有 secret 列；备注字段不是凭据
-- 存放处——Web 表单不提供凭据输入，响应也永不回显任何凭据形态的
-- 数据）。真正的凭据值属于既有 write-only 边界（RSSHub 凭据库等，
-- 值写后只存哈希），本表只引导用户去那些受控入口更新。
--
-- status ∈ active | dismissed；dismiss 是 set 语义（行保留，可重新
-- 激活=再次 renew）；renewed_count 记录续期次数（审计友好）。

CREATE TABLE IF NOT EXISTS new208_credential_reminders (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    source_label TEXT,
    expires_on TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dismissed')),
    renewed_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_new208_reminders_feed
    ON new208_credential_reminders (feed_url, expires_on);
