-- 0072 (N032): content-loss recovery support.
--
-- search_entries.content_max_len — the largest content length ever seen for
-- this entry (small integer column; survives rebuilds via the staging
-- INSERT). Used to decide when the CURRENT content is suspiciously shorter
-- than the largest previously-seen variant (< 40%).
-- search_entries.content_hash — hash of the latest delivered content; the
-- N031 revision trigger (SAME id, changed hash) and the incremental sync's
-- change detection both key off it.
--
-- entry_content_variants — the ONE bounded exception where article content
-- bytes are kept outside FreshRSS. Why the bytes at all: the recovery
-- choice ("show the last known full version") is meaningless without the
-- actual bytes; a summary cannot be re-rendered as the article. Bound:
-- exactly one row per entry (keep_latest=1, rotated on write), and a write
-- is rejected above 200 KB so the table can never shadow the projection.
-- Rows are derived from FreshRSS deliveries and are rebuildable input
-- history, not an RSS-domain shadow store.

ALTER TABLE search_entries ADD COLUMN content_max_len INTEGER NOT NULL DEFAULT 0;
ALTER TABLE search_entries ADD COLUMN content_hash TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS entry_content_variants (
    entry_ref TEXT PRIMARY KEY,
    content_html TEXT NOT NULL,
    captured_at TEXT NOT NULL
);
