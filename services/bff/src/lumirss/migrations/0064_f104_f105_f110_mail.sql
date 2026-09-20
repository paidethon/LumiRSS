-- 0064: W6 邮件域（F104 解析对照 / F105 过滤规则 / F110 会话串联）。
-- F104：ingest 时的有界结构快照（multipart 树 + 计数，JSON ≤2KB）。
ALTER TABLE mail_bridge_entries ADD COLUMN structure_json TEXT;

-- F110：会话串联头（仅存可信解析结果；message_id 列已有身份语义）。
ALTER TABLE mail_bridge_entries ADD COLUMN in_reply_to TEXT;
ALTER TABLE mail_bridge_entries ADD COLUMN references_head TEXT;

-- F105：每列表接收规则（首条命中决定 allow/deny；无规则 = allow）。
CREATE TABLE mail_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_uuid TEXT NOT NULL,
    field TEXT NOT NULL CHECK (field IN ('from', 'subject')),
    op TEXT NOT NULL CHECK (op IN ('contains', 'equals')),
    value TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('allow', 'deny')),
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX mail_rules_list ON mail_rules (list_uuid, priority);

-- F105：deny 计数（独立计数列；deny 邮件不入 feed 但要如实留痕）。
ALTER TABLE mail_bridge_lists ADD COLUMN skipped_count INTEGER NOT NULL DEFAULT 0;
