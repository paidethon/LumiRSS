-- FIX-144: whole-article translation cache identity gains the glossary
-- version. The page-level translation attaches the LIVE glossary block
-- to its prompt, so a glossary write must invalidate exactly like the
-- per-block segment cache (0005, FIX-305) — otherwise old results are
-- misattributed to the new glossary. Legacy rows default to '' (the
-- initial glossary version), so upgrading alone invalidates nothing;
-- the first glossary write moves the version forward from there.

ALTER TABLE ai_translations ADD COLUMN glossary_version TEXT NOT NULL DEFAULT '';

DROP INDEX ai_translations_cache_identity;

CREATE UNIQUE INDEX ai_translations_cache_identity ON ai_translations (
    entry_ref, content_hash, provider, model, prompt_version, target_language,
    glossary_version
);
