-- 0322: NEW-399 帮助文档反馈定位 —— 段落级问题 + 版本锚点 + 处理回复。
--
-- doc_path 存相对 docs/ 的路径（写入时只读校验文件真实存在并记录
-- 锚点是否能在文档内找到——anchorFound 是检测结论，不是保证）；
-- version 取提交时的构建版本，管理员据此定位「哪个版本的文档在
-- 说什么」。resolve 后状态 revised 终态 + 回复写回本人列表，并经
-- NEW-391 record_event 落一条真实「帮助已回复」通知。

CREATE TABLE IF NOT EXISTS help_doc_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    doc_path TEXT NOT NULL,
    anchor TEXT NOT NULL DEFAULT '',
    anchor_found INTEGER,
    version TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'revised')),
    revision_note TEXT NOT NULL DEFAULT '',
    reply TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_help_feedback_user_time
    ON help_doc_feedback(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_help_feedback_status
    ON help_doc_feedback(status, created_at ASC);
