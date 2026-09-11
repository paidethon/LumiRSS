-- 0015: Unified tags (phase2 G8). Three origins (manual/source/ai);
-- AI suggestions land as status='suggested' and NEVER enter filtered
-- results or the graph until explicitly accepted (adopt = the suggested
-- row is upgraded in place — no duplicate rows, no pollution).
CREATE TABLE tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE item_tags (
  item_ref TEXT NOT NULL,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  origin TEXT NOT NULL CHECK (origin IN ('manual', 'source', 'ai')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suggested')),
  created_at TEXT NOT NULL,
  UNIQUE (item_ref, tag_id, origin)
);

CREATE INDEX ix_item_tags_ref ON item_tags(item_ref);
CREATE INDEX ix_item_tags_tag ON item_tags(tag_id);
