-- 0022: Library durability batch (quality closure 2026-09-15).
--
-- (a) RSS bookmarks get a real uniqueness guarantee. Only a plain index
--     existed on rss_item_ref, so double-submit / concurrent bookmark of
--     the same entry created duplicate rows. Existing duplicates keep the
--     earliest (created_at, item_uuid); later duplicates lose their
--     identity row (payload rows cascade) and their search projection row.
--     The same pass sweeps identity rows orphaned by the pre-transaction
--     create path (bookmark + clip kinds only — each other kind has its
--     own payload table with different keying).
-- (b) Hot list queries get covering indexes: bookmark keyset page
--     (created_at, item_uuid), read-later timeline (workspace_id,
--     added_at), inbox per-source page (source_uuid, created_at).
-- Forward-only: keeps the earliest row per duplicate group, drops nothing
-- else; fresh databases and v21 databases both end at v22.

DELETE FROM search_library
WHERE ref IN (
  SELECT 'library:' || b.item_uuid FROM library_bookmarks b
  WHERE b.rss_item_ref IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM library_bookmarks keep
      WHERE keep.rss_item_ref = b.rss_item_ref
        AND (keep.created_at < b.created_at
             OR (keep.created_at = b.created_at AND keep.item_uuid < b.item_uuid))
    )
);

DELETE FROM library_items
WHERE kind = 'bookmark' AND uuid IN (
  SELECT b.item_uuid FROM library_bookmarks b
  WHERE b.rss_item_ref IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM library_bookmarks keep
      WHERE keep.rss_item_ref = b.rss_item_ref
        AND (keep.created_at < b.created_at
             OR (keep.created_at = b.created_at AND keep.item_uuid < b.item_uuid))
    )
);

DELETE FROM library_items
WHERE kind = 'bookmark'
  AND uuid NOT IN (SELECT item_uuid FROM library_bookmarks);

DELETE FROM library_items
WHERE kind = 'clip'
  AND uuid NOT IN (SELECT item_uuid FROM library_clips);

CREATE UNIQUE INDEX ux_bookmarks_rss_ref
  ON library_bookmarks(rss_item_ref) WHERE rss_item_ref IS NOT NULL;

DROP INDEX IF EXISTS ix_bookmarks_rss_ref;

CREATE INDEX ix_bookmarks_created ON library_bookmarks(created_at, item_uuid);
CREATE INDEX ix_workspace_items_added ON workspace_items(workspace_id, added_at);
CREATE INDEX ix_inbox_source_created ON library_inbox(source_uuid, created_at);
