-- 0074 (N034): published-time credibility flags on the projection row.
--
-- Bitmask classified AT INGEST (missing / no_timezone / future / too_old).
-- received ordering reuses the existing fetched_at column (the projection
-- ingest timestamp); no separate received_at column is added.

ALTER TABLE search_entries ADD COLUMN time_flags INTEGER NOT NULL DEFAULT 0;
