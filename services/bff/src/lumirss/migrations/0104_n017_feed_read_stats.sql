-- 0106: N017 来源清理建议 —— per-feed read recency.
--
-- No per-feed "last opened" tracking exists in Lumi (FreshRSS owns read
-- state and exposes no read timestamps), so the BFF keeps a tiny derived
-- projection of its OWN write path: every PATCH /entries/{ref}/state
-- that sets read=true bumps last_read_at for the entry's feed. The
-- table is a behavior stat (rebuildable, never content): it starts
-- empty on upgrade and only reflects reads made after it exists — the
-- suggestions endpoint reports that basis honestly instead of guessing.
CREATE TABLE feed_read_stats (
  feed_url TEXT PRIMARY KEY,
  last_read_at TEXT NOT NULL,
  read_total INTEGER NOT NULL DEFAULT 1
);
