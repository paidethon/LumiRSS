-- 0260: NEW-336 讨论标记待答与已解答 —— 发起者把讨论标为问题（创建
-- 即问题），选中有用回复后标记解决；完整讨论永远保留（不删除任何
-- 回复，解决只是状态位 + 选中回复引用）。

CREATE TABLE IF NOT EXISTS space_discussions (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    entry_ref TEXT,
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    resolved_reply_id TEXT,
    resolved_at TEXT,
    asked_by TEXT NOT NULL,
    asked_by_username TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_discussion_replies (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    entry_ref TEXT,
    author_user_id TEXT NOT NULL,
    author_username TEXT NOT NULL,
    body TEXT NOT NULL,
    helpful INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_space_discussions_space
    ON space_discussions (space_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_space_discussion_replies_discussion
    ON space_discussion_replies (discussion_id, created_at ASC);
