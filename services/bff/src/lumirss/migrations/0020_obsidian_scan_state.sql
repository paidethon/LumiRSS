-- 0020: explicit truncation flag for the bounded obsidian projection
-- (Gate 4 / P0-09d). Notes whose body/tags/wikilinks/title exceeded the
-- projection caps are marked on the row and in scan reports instead of
-- being silently shortened. Additive, backfills 0.
ALTER TABLE obsidian_notes ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0;
