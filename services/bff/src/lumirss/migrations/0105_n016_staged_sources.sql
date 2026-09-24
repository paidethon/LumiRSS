-- 0105: N016 暂存待评估来源 + N011 组合包凭据草稿.
--
-- staged_sources is a staging pool OUTSIDE the RSS domain: rows are
-- neither subscriptions nor content and never count toward unread.
--   origin='staging'      — N016: a URL parked for evaluation together
--                           with a bounded preview sample (≤10 entries,
--                           rebuildable metadata only);
--   origin='bundle_draft' — N011: a bundle import item whose source type
--                           needs credentials (api/mail). The bundle is
--                           credential-free by construction, so these
--                           rows import as DISABLED drafts the operator
--                           must re-create deliberately.
-- source_type records why credentials are needed; enabled=0 for drafts.
CREATE TABLE staged_sources (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  added_at TEXT NOT NULL,
  note TEXT,
  sample_json TEXT,
  source_type TEXT NOT NULL DEFAULT 'rss' CHECK (source_type IN ('rss', 'api', 'mail', 'inbox')),
  origin TEXT NOT NULL DEFAULT 'staging' CHECK (origin IN ('staging', 'bundle_draft')),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE INDEX ix_staged_sources_added ON staged_sources(added_at DESC);
