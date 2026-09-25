-- 0094: N150 tag merge undo.
--
-- Before a merge executes, the source tag's bindings are snapshotted
-- into this table so POST /tags/merge/undo can restore them (the
-- target keeps its merged bindings; the source tag is recreated).
-- Singleton per user: id is pinned to 1 with CHECK — a new merge
-- REPLACES the previous snapshot (only the latest merge is undoable).
-- The row intentionally SURVIVES a successful undo: a second undo
-- attempt must fail with 409 (the source tag now exists again), not
-- silently double-restore. TTL 24h is enforced in code (created_at).
-- bindings_json: [{itemRef, origin, status, createdAt}, ...].

CREATE TABLE tag_merge_undo (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  source_tag_id INTEGER NOT NULL,
  source_tag_name TEXT NOT NULL,
  target_tag_id INTEGER NOT NULL,
  bindings_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
