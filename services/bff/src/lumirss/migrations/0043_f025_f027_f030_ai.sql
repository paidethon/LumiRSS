-- 0043: F025 AI 输入范围控制 + F027 摘要版本 + F030 问答模板。
--
-- F025：ai_summaries 记录实际发送给 Provider 的字符数与截断标记
-- （诚实口径，不估算 token）；
-- F027：摘要重生成保留旧版本（每 entry+content_hash 最多 3 版，FIFO）；
-- F030：问答模板（与具体文章无关的纯文本模板）。

ALTER TABLE ai_summaries ADD COLUMN input_chars INTEGER;
ALTER TABLE ai_summaries ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS ai_summary_versions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    entry_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    summary TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_summary_versions_lookup
    ON ai_summary_versions (entry_ref, content_hash, created_at);

CREATE TABLE IF NOT EXISTS qa_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
