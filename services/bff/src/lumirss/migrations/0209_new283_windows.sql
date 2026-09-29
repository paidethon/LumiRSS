-- 0209: NEW-283 简报截稿窗口 —— 周期简报的时区 + 截止点 + 周期。
--
-- 每用户单行（id='default'）。cutoff_time 是该时区的墙钟 'HH:MM'：
-- 截止点之后发布的文章属于下一期（迟到），可手动调回（pullBack）。
-- 时区必须显式：存 IANA 名称，边界计算用 ZoneInfo，绝不假设服务器
-- 本地时区。period_days 限 1(日报)/7(周报)。

CREATE TABLE IF NOT EXISTS briefing_windows (
    id TEXT PRIMARY KEY,
    timezone TEXT NOT NULL,
    cutoff_time TEXT NOT NULL,
    period_days INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
