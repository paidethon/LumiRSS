-- 0325: R19 邮件简报发送账本（外发摘要逐次记录）。
--
-- digest_settings.last_sent_at / last_error 只保留「最后一次」结果；
-- 本表是逐次发送账本：成功行持久化正文快照（body_text/body_html）
-- 供已发送内容页回看；失败行保留错误与逐收件人账目（recipients_json）
-- 供重试——重试只投递账目中尚未成功的收件人，绝不重复投递。
-- items_json 保存当次的服务端派生条目（标题/来源），重试按同一快照
-- 重组正文，不凭空重选。
-- dedupe_key 与 DigestScheduler 的 RuntimeLeases 小时窗口互补：同一
-- 调度窗口的补写 UPDATE 同一行（对齐 gpt_digest_issues 的期号惯例）；
-- '' = 手动发送，不去重。收件人地址明文只存 per-user 库——永不进
-- 日志；API 层对非管理员脱敏展示。
CREATE TABLE IF NOT EXISTS newsletter_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'sent',
    body_text TEXT,
    body_html TEXT,
    items_json TEXT NOT NULL DEFAULT '[]',
    dedupe_key TEXT NOT NULL DEFAULT '',
    provider_receipt TEXT NOT NULL DEFAULT '',
    item_count INTEGER NOT NULL DEFAULT 0,
    recipient_count INTEGER NOT NULL DEFAULT 0,
    recipients_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_newsletter_issues_created
    ON newsletter_issues (created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_newsletter_issues_dedupe
    ON newsletter_issues (dedupe_key) WHERE dedupe_key <> '';
