-- 0071 (N031): entry revision history — bounded side records captured when
-- FreshRSS re-delivers an entry with the SAME id but a changed content hash.
--
-- NOT a second content store: rows hold only bounded metadata (timestamps,
-- title change flag, structural diff summary, content hashes) — never the
-- full article body (the projection stays non-authoritative / rebuildable).
-- Cap (5 revisions per entry) is enforced at write time with an INSERT-time
-- prune, not here.

CREATE TABLE IF NOT EXISTS entry_revisions (
    id INTEGER PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    title_changed INTEGER NOT NULL DEFAULT 0,
    prev_title TEXT NOT NULL DEFAULT '',
    new_title TEXT NOT NULL DEFAULT '',
    content_diff_summary TEXT NOT NULL DEFAULT '{}',
    prev_hash TEXT NOT NULL DEFAULT '',
    new_hash TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_entry_revisions_ref
    ON entry_revisions(entry_ref, id DESC);
