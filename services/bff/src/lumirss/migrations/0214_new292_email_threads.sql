-- 0218: NEW-292 邮件会话串联 —— 按真实字段（In-Reply-To / References）
-- 把用户导入的同一邮件往返组织成会话；字段不足允许手动关联。
--
-- email_threads：一行 = 一个会话；thread_id 在 email_materials 上：
--   references = 导入时按头部字段自动归入（真实证据）；
--   manual     = 用户手动关联（字段不足时的诚实兜底）；
--   none       = 单封未成串。
-- subject_hint 只作展示提示，绝不参与匹配（只信真实字段 + 用户手动）。

CREATE TABLE IF NOT EXISTS email_threads (
    id TEXT PRIMARY KEY,
    subject_hint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

ALTER TABLE email_materials ADD COLUMN thread_id TEXT NOT NULL DEFAULT '';
ALTER TABLE email_materials ADD COLUMN link_mode TEXT NOT NULL DEFAULT 'none';

CREATE INDEX IF NOT EXISTS idx_email_materials_thread
    ON email_materials(thread_id);
