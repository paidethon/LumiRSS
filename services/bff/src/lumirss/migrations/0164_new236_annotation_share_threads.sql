-- 0146: NEW-236 批注回复提醒 —— 明确共享批注的回复串（控制库表）。
--
-- 迁移集同时应用于控制库与每个 per-user 库；线程/回复表只在控制库
-- 使用（跨用户是控制关注点，与 ai_usage 同一先例）。行存在的唯一
-- 前提是批注所有者的显式 share 动作——私人批注绝不自动进入共享面。
--
-- annotation_share_threads：owner 显式共享批注给指定成员（快照
-- excerpt/note/entry_ref 作为收件人可见的「原上下文」，共享时点快照，
-- 不自动跟随后续编辑）；dismissed_at = 收件人关闭该串提醒；
-- unread_for_recipient = 收件人未读回复数。
-- annotation_share_replies：串内回复（作者只能是 owner 或收件人）。

CREATE TABLE IF NOT EXISTS annotation_share_threads (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    annotation_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    shared_with_user_id TEXT NOT NULL,
    shared_with_username TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dismissed_at TEXT,
    unread_for_recipient INTEGER NOT NULL DEFAULT 0,
    UNIQUE (annotation_id, shared_with_user_id)
);

CREATE TABLE IF NOT EXISTS annotation_share_replies (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    author_user_id TEXT NOT NULL,
    author_username TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_annotation_share_threads_recipient
    ON annotation_share_threads (shared_with_user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_annotation_share_replies_thread
    ON annotation_share_replies (thread_id, created_at ASC);
