-- 0269: NEW-346 设备信任期限 —— 当前设备（UA 族|平台指纹）的敏感
-- 操作信任到期日。密码复核后授予；到期必须重新验证。
-- 明确不触碰 auth_sessions：授予/续期绝不延长服务端会话本身。

CREATE TABLE IF NOT EXISTS device_trust_grants (
    device_fingerprint TEXT PRIMARY KEY,
    device_label TEXT NOT NULL,
    trusted_until TEXT NOT NULL,
    created_at TEXT NOT NULL,
    renewed_at TEXT
);
