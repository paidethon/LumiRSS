-- 0015: Lumi-owned application state.
--
-- Ownership boundary: FreshRSS remains the RSS-domain source of truth.
-- These tables hold ONLY Lumi-owned state (AI generation/cache records and
-- allow-listed non-secret server settings). There are deliberately NO
-- shadow tables for feeds, entries, subscriptions, categories, read state
-- or starred state.

CREATE TABLE lumi_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE ai_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('not_generated', 'generating', 'success', 'failed')
    ),
    summary_text TEXT,
    failure_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ai_summaries_cache_identity ON ai_summaries (
    entry_ref, content_hash, provider, model, prompt_version, language
);
