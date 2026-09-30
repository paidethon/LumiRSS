-- 0302: NEW-379 用户问题工单 —— 工单正文只来自用户显式提交；
-- 系统绝不自动附带该用户的文章/资料库私人正文。指派与回复有
-- 状态机（open → assigned → answered → closed；closed 终态）。

CREATE TABLE IF NOT EXISTS admin_tickets (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    submitted_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'assigned', 'answered', 'closed')),
    assigned_to TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_tickets_status
    ON admin_tickets(status, created_at DESC);

CREATE TABLE IF NOT EXISTS admin_ticket_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_ticket_replies_ticket
    ON admin_ticket_replies(ticket_id, id);
