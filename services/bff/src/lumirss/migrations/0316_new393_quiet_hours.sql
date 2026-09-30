-- 0316: NEW-393 提醒静默时段 —— 每用户一条应用内提醒静默设置。
--
-- start/end 为用户所选时区墙钟 HH:MM；end < start 表示跨午夜；
-- start = end 拒绝（空窗口）。time_zone 必须是可解析的 IANA 时区
-- （ZoneInfo 校验），不合法直接 422，绝不静默回退服务器时区。
-- 静默不影响事件落库（0314 照常记录），只影响呈现：静默期间不推送
-- 打扰，结束后以汇总摘要呈现窗口内的未读事件。

CREATE TABLE IF NOT EXISTS notification_quiet_hours (
    user_id TEXT PRIMARY KEY,
    start_hhmm TEXT NOT NULL,
    end_hhmm TEXT NOT NULL,
    time_zone TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
