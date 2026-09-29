-- 0256: NEW-332 共享内容审批队列 —— 空间开启投稿审批后，成员投稿先
-- 进 pending；pending 只对投稿者本人与管理者可见，绝不公开给全体；
-- 管理者批准/退回（退回必须带原因），投稿者能看到自己的待审与退回原因。

CREATE TABLE IF NOT EXISTS space_contributions (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    note TEXT,
    section_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    reviewed_by TEXT,
    reviewed_by_username TEXT,
    reviewed_at TEXT,
    submitted_by TEXT NOT NULL,
    submitted_by_username TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_space_contributions_space
    ON space_contributions (space_id, status, created_at DESC);
