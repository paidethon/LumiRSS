-- 0010: API Sources v1 (phase2 M3).
-- Config lives in Lumi; converted entries live ONLY in FreshRSS (the
-- Atom endpoint is a derived, rebuildable artifact — never a second
-- content database).
CREATE TABLE api_sources (
  uuid TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  items_expr TEXT NOT NULL,
  field_map TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  secret TEXT NOT NULL UNIQUE,
  etag TEXT,
  last_status TEXT,
  last_success_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX ix_api_sources_created ON api_sources(created_at);
