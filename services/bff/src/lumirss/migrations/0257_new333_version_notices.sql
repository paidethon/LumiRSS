-- 0257: NEW-333 共读内容版本通知 —— 成员显式报告某共享条目出现新版本
-- 后，系统为本空间内该条目的**讨论参与者**（提问者/回复者）逐人建
-- 待核对提醒；参与者可标记「已重新核对」。
--
-- 诚实边界：新版本正文不跨用户库复制（per-user 分库）；通知只携带
-- 条目 ref + 版本标签 + 报告人摘要，接收方在自己的阅读器里重新核对。

CREATE TABLE IF NOT EXISTS space_version_notices (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    version_label TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    reported_by TEXT NOT NULL,
    reported_by_username TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_version_notice_acks (
    notice_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    user_id TEXT NOT NULL,
    acknowledged_at TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (notice_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_space_version_notices_space
    ON space_version_notices (space_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_space_version_notice_acks_user
    ON space_version_notice_acks (user_id, acknowledged_at);
