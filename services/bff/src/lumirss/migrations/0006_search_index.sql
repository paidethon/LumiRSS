-- 0006: Global search index (0022).
--
-- A derived, 100%-rebuildable projection used ONLY for full-text search.
-- FreshRSS remains the RSS-domain source of truth: deleting these tables
-- loses no RSS state, and every row is re-created from FreshRSS by the
-- sync service. This is not a shadow copy of the RSS domain — no entry
-- is created, updated or read here for any non-search purpose.
--
-- Design note: search runs parameterized LIKE queries (SQL-side escaping)
-- instead of an FTS5 MATCH index. At single-user scale a full scan is
-- milliseconds, substring semantics work identically for CJK and Latin,
-- and short (1-2 char) queries need no trigram fallback path. Revisit
-- FTS5 MATCH only if real datasets outgrow this.

CREATE TABLE IF NOT EXISTS search_entries (
    id INTEGER PRIMARY KEY,
    item_id TEXT UNIQUE NOT NULL,
    entry_ref TEXT UNIQUE NOT NULL,
    feed_url TEXT NOT NULL,
    feed_title TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    content_text TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    starred INTEGER NOT NULL DEFAULT 0,
    fetched_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_entries_published
    ON search_entries(published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_search_entries_feed
    ON search_entries(feed_url);

-- Feed -> category projection, refreshed on every sync from the
-- FreshRSS subscription list; lets search filter by category with one
-- bound parameter instead of interpolating a feed-id list.
CREATE TABLE IF NOT EXISTS search_feeds (
    feed_url TEXT PRIMARY KEY,
    feed_title TEXT NOT NULL DEFAULT '',
    category_id TEXT,
    refreshed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS search_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
