-- Browser-managed AI profiles.
--
-- Metadata only: labels, provider type, base URL, model and the enabled
-- flag. API keys NEVER live here — they are write-only entries in the
-- SecretsStore (secrets.json, outside lumi.sqlite), so a full backup of
-- this database cannot contain a key by construction (AD-0018-6).
-- Purpose → profile mapping is a JSON document in lumi_settings
-- (key 'ai.purposes'), not a column, so unknown future purposes are
-- additive.

CREATE TABLE ai_profiles (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
