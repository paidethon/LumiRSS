-- 0213: NEW-288 跨期主题追踪 —— 用户给简报条目挂主题，跨期聚合同一
-- 主题的相关文章。briefing_topics 每用户库名唯一（同建同取，幂等）；
-- briefing_topic_entries 保留期次位置（briefing_id + item_id），链上
-- 顺序 = 期次确认时间 + 期次内条目位置，后挂的就是后续更新。

CREATE TABLE IF NOT EXISTS briefing_topics (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_briefing_topics_name
    ON briefing_topics (name);

CREATE TABLE IF NOT EXISTS briefing_topic_entries (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    briefing_id TEXT NOT NULL,
    briefing_item_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    noted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefing_topic_entries_topic
    ON briefing_topic_entries (topic_id, noted_at ASC);
