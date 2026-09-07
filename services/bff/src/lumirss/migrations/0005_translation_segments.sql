-- Gate: structured per-block translation cache (双语对照).
--
-- Same ownership boundary as 0002: FreshRSS remains the RSS-domain source
-- of truth; this table holds ONLY Lumi-owned derived translation segments
-- keyed by the normalized block text hash, so a content change invalidates
-- its own rows and never serves stale pairs.

CREATE TABLE ai_translation_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_ref TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    target_language TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('success', 'failed')
    ),
    translated_text TEXT,
    failure_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ai_translation_segments_identity ON ai_translation_segments (
    entry_ref, block_index, block_hash, provider, model, prompt_version,
    target_language
);

CREATE INDEX ai_translation_segments_entry ON ai_translation_segments (
    entry_ref, target_language
);
