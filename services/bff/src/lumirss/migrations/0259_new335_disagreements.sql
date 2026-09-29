-- 0259: NEW-335 共读分歧记录 —— 把不同结论及各自引用**并列**保存；
-- 空间成员可补充证据；不强制生成统一结论（无统一结论字段，闭合仅
-- 是可选的停止写入）。

CREATE TABLE IF NOT EXISTS space_disagreements (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    entry_ref TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_by TEXT NOT NULL,
    created_by_username TEXT NOT NULL,
    closed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_disagreement_positions (
    id TEXT PRIMARY KEY,
    disagreement_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    author_user_id TEXT NOT NULL,
    author_username TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (disagreement_id, author_user_id)
);

CREATE TABLE IF NOT EXISTS space_disagreement_evidence (
    id TEXT PRIMARY KEY,
    disagreement_id TEXT NOT NULL,
    position_id TEXT,
    added_by TEXT NOT NULL,
    added_by_username TEXT NOT NULL,
    note TEXT NOT NULL,
    ref TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_space_disagreements_space
    ON space_disagreements (space_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_space_disagreement_positions_disagreement
    ON space_disagreement_positions (disagreement_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_space_disagreement_evidence_disagreement
    ON space_disagreement_evidence (disagreement_id, created_at ASC);
