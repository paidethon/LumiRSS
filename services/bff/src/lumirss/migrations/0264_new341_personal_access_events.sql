-- 0264: NEW-341 个人数据访问记录 —— 受授权共享入口经 Lumi 读取本人
-- 数据的最小事件（purpose + entry 标签 + 时间）。
--
-- 诚实边界（与表结构一致，见 new341_access_log.py 的 UNRECORDED_NOTES）：
-- 不记录访问者 IP / User-Agent / 查询参数；FreshRSS 直接服务的原生
-- 订阅读取不经过 Lumi，无法记录；用户本人浏览器会话的读取不是
-- 「被共享」事件，不记录。

CREATE TABLE IF NOT EXISTS personal_access_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose TEXT NOT NULL,
    entry TEXT NOT NULL,
    accessed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_personal_access_events_time
    ON personal_access_events(accessed_at DESC);
