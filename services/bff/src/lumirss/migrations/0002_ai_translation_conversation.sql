-- 0016: AI translation cache + article-scoped conversation persistence.
--
-- Same ownership boundary as 0001: FreshRSS remains the RSS-domain source
-- of truth. These tables hold ONLY Lumi-owned AI state (translation cache
-- rows and per-article conversation messages). No feed/entry/read/starred
-- shadow tables.

CREATE TABLE ai_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    target_language TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('not_generated', 'generating', 'success', 'failed')
    ),
    translated_title TEXT,
    translated_text TEXT,
    failure_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ai_translations_cache_identity ON ai_translations (
    entry_ref, content_hash, provider, model, prompt_version, target_language
);

CREATE TABLE ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- One conversation per article content version: changed content => new
-- hash => a fresh conversation (old rows are simply no longer referenced).
CREATE UNIQUE INDEX ai_conversations_entry ON ai_conversations (
    entry_ref, content_hash
);

CREATE TABLE ai_conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX ai_conversation_messages_conversation ON ai_conversation_messages (
    conversation_id
);
