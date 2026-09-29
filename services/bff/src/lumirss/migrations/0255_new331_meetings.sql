-- 0255: NEW-331 共读会议资料单 —— 成员把明确共享的文章和待讨论问题
-- 组成一次会议资料单；结束后保存结论与出处。
--
-- 快照语义（与 NEW-236 同型）：资料项的 title/excerpt 在成员显式添加
-- 时点固化，绝不自动跟随私人库后续变化。结论（outcomes）只在会议
-- closed 之后允许写入——「结束后保存结论」。

CREATE TABLE IF NOT EXISTS space_meetings (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_by TEXT NOT NULL,
    created_by_username TEXT NOT NULL,
    closed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_meeting_items (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    question TEXT,
    added_by TEXT NOT NULL,
    added_by_username TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_meeting_outcomes (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    entry_ref TEXT,
    summary TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_by_username TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_space_meetings_space
    ON space_meetings (space_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_space_meeting_items_meeting
    ON space_meeting_items (meeting_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_space_meeting_outcomes_meeting
    ON space_meeting_outcomes (meeting_id, created_at ASC);
