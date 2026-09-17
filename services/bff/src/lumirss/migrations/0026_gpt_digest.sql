-- 0026: GPT 日报（M4）——自有生成内容域，与上游 RSS 原文分离。
--
-- gpt_digest_settings：单行配置（调度、窗口、选材上限）。
--   last_issue_key 记录最近一次成功发布的期号（配置时区墙钟日期），
--   与 mail_digest 的 last_sent_at 一样承担「重启幂等」边界标记。
-- gpt_digest_issues：已生成的期刊。issue_key 唯一——同一窗口并发/
--   重启最多产生一个逻辑发布结果（修订 = UPDATE 同一行，不产生新期）。
--   refs_json 保存服务端已解析的来源引用（上游标题/URL 由服务端写入，
--   模型只允许引用服务端分配的 source id）。
-- 订阅 token 存 SecretsStore（gpt_digest_feed_token），不进 SQLite。

CREATE TABLE IF NOT EXISTS gpt_digest_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    hour INTEGER NOT NULL DEFAULT 8,
    timezone TEXT NOT NULL DEFAULT '',
    window_hours INTEGER NOT NULL DEFAULT 24,
    limit_count INTEGER NOT NULL DEFAULT 12,
    per_source_cap INTEGER NOT NULL DEFAULT 2,
    last_issue_key TEXT,
    last_error TEXT
);

INSERT INTO gpt_digest_settings (id) SELECT 1
WHERE NOT EXISTS (SELECT 1 FROM gpt_digest_settings WHERE id = 1);

CREATE TABLE IF NOT EXISTS gpt_digest_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'published',
    title TEXT NOT NULL,
    body_html TEXT NOT NULL,
    sections_json TEXT NOT NULL,
    refs_json TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    published_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gpt_digest_issues_key
    ON gpt_digest_issues (issue_key DESC);
