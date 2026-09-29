-- 0181: NEW-255 事件时间线编辑器。
--
-- research_timeline_events：从本人材料里登记的事件行。核心区分：
--   - event_at    事件发生时间（用户按自己掌握的精度登记，原文存储，
--                 不统一改写成机器时间——「约1990年代」也是合法值）；
--   - reported_at 报道时间（媒体什么时候说的；可选）。
-- 两者只有都能解析成日期前缀（YYYY-MM-DD）时才计算 reported_days_after
-- 差值；解析不了就诚实返回 null，绝不猜。
--
-- item_ref：出处（只引用不复制）。

CREATE TABLE IF NOT EXISTS research_timeline_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    event_at TEXT NOT NULL,
    reported_at TEXT,
    item_ref TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_timeline_events_project
    ON research_timeline_events (project_id, created_at ASC);
