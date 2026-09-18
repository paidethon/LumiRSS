-- 0035: F21 个人术语本 —— 用户自建的术语与解释（不默认调用 AI）。
--
-- 同词不同含义可并存（term 不唯一）；source_ref 可选关联原文
-- （rss:<entryRef> / library:<uuid>），供「返回原文」使用。

CREATE TABLE IF NOT EXISTS glossary_terms (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL,
    definition TEXT NOT NULL,
    source_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_glossary_term ON glossary_terms (term);
