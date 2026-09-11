-- 0009: web clips, offline snapshot assets, library search projection
-- (phase2 M2). Clips are Lumi-owned content (kind='clip'); assets are
-- user-saved snapshots (kind='snapshot') — never LRU-evictable, only
-- explicit user deletion or the explicit quota policy. search_library is
-- a derived, rebuildable projection in the same plain-table + LIKE shape
-- as the existing search_entries (no FTS5: the RSS leg does not use it).
CREATE TABLE library_clips (
  item_uuid TEXT PRIMARY KEY REFERENCES library_items(uuid) ON DELETE CASCADE,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  byline TEXT,
  content_html TEXT NOT NULL,
  content_text TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_clips_url ON library_clips(url);
CREATE INDEX ix_clips_created ON library_clips(created_at);

CREATE TABLE library_assets (
  uuid TEXT PRIMARY KEY,
  item_uuid TEXT NOT NULL REFERENCES library_items(uuid) ON DELETE CASCADE,
  path TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  mime TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_assets_item ON library_assets(item_uuid);
CREATE INDEX ix_assets_sha ON library_assets(sha256);

-- Derived, rebuildable library search projection (plain table + LIKE,
-- same query style as search_entries; FTS5 deliberately not introduced).
CREATE TABLE IF NOT EXISTS search_library (
  ref TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  url TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX ix_search_library_title ON search_library(title);
