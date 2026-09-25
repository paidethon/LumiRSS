-- N008 新设备登录提醒：会话标注设备 + 登录事件流（控制库）。
-- auth_sessions.device_label：登录时的 UA 族 + 平台（如 "Chrome/Linux"），
-- 仅用于展示（绝不存原始 token/秘密）。login_events：每次登录一行，
-- kind = new_device（指纹首次出现）| login（已知设备重复登录）；
-- fingerprint = UA族+平台 的哈希（同设备再登录 → 不再产生 new_device）。
ALTER TABLE auth_sessions ADD COLUMN device_label TEXT;

CREATE TABLE IF NOT EXISTS login_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  device_label TEXT NOT NULL DEFAULT '',
  fingerprint TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  seen INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_login_events_user_created
  ON login_events(user_id, created_at DESC);
