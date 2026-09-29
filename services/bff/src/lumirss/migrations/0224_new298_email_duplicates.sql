-- 0224: NEW-298 邮件重复识别复核 —— Message-ID 相同但正文不同的样本
-- 列入冲突队列，由用户选择保留版本。
--
-- email_duplicate_conflicts：一行 = 一条待复核冲突。incoming_json 保存
-- 未入库的来件完整解析结果（含附件元数据；解决时按用户选择走 0217
-- 的 insert_material 写入或丢弃）。status: pending/kept_existing/
-- kept_incoming/kept_both。

CREATE TABLE IF NOT EXISTS email_duplicate_conflicts (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    existing_id TEXT NOT NULL,
    existing_digest TEXT NOT NULL DEFAULT '',
    incoming_digest TEXT NOT NULL DEFAULT '',
    incoming_json TEXT NOT NULL DEFAULT '{}',
    filename TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    result_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_email_dup_conflicts_status
    ON email_duplicate_conflicts(status);
