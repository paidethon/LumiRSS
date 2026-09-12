-- 0017: tag names dedupe case-insensitively (P0-10f). SQLite's NOCASE
-- collation folds ASCII case (CJK names are unaffected — they never had
-- case). Existing case-variant groups merge into the lowest-id row.
-- Order matters: bindings that would collide after the remap fold FIRST
-- (active preferred, then lowest rowid), so the UPDATE never trips the
-- item_tags UNIQUE constraint. Duplicate tag rows go away, and a NOCASE
-- unique index keeps future variants out at the engine level. Queries
-- use `name = ? COLLATE NOCASE`; forward-only, no data dropped.
CREATE TEMP TABLE tag_map (old_id INTEGER PRIMARY KEY, new_id INTEGER NOT NULL);
INSERT INTO tag_map (old_id, new_id)
SELECT t.id, (SELECT MIN(t2.id) FROM tags t2 WHERE t2.name = t.name COLLATE NOCASE) FROM tags t;
DELETE FROM item_tags
WHERE EXISTS (
  SELECT 1 FROM item_tags AS keep
  WHERE keep.item_ref = item_tags.item_ref
    AND keep.origin = item_tags.origin
    AND (SELECT new_id FROM tag_map WHERE old_id = keep.tag_id) = (SELECT new_id FROM tag_map WHERE old_id = item_tags.tag_id)
    AND (
      (keep.status = 'active' AND item_tags.status != 'active')
      OR (keep.status = item_tags.status AND keep.rowid < item_tags.rowid)
    )
);
UPDATE item_tags
SET tag_id = (SELECT new_id FROM tag_map WHERE old_id = item_tags.tag_id);
DELETE FROM tags
WHERE id IN (SELECT old_id FROM tag_map WHERE old_id != new_id);
CREATE UNIQUE INDEX ix_tags_name_nocase ON tags(name COLLATE NOCASE);
