-- 0021: generic Inbox push source (phase2 knowledge-workbench foundations).
--
-- An Inbox connector is a machine-to-machine push endpoint: external
-- scripts/agents POST authenticated JSON items that land as Lumi-owned
-- content. Identity rows reuse the EXISTING library_items kind
-- 'api_item' — the enum CHECK cannot be extended without rebuilding the
-- parent table, and a parent-table rebuild under foreign_keys=ON would
-- cascade-wipe every existing bookmark/clip/snapshot row (implicit
-- DELETE on DROP TABLE). ADR 0004 clarifies the kind's semantics:
-- api_item = "content object ingested through Lumi's HTTP API" (the
-- pull-converted api-source flow keeps living in FreshRSS and never
-- creates library rows).
--
-- Purely additive: fresh databases and v20 databases both end at v21
-- with all prior data intact.

CREATE TABLE inbox_sources (
  uuid TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  secret TEXT NOT NULL,
  last_success_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE library_inbox (
  item_uuid TEXT PRIMARY KEY REFERENCES library_items(uuid) ON DELETE CASCADE,
  source_uuid TEXT NOT NULL REFERENCES inbox_sources(uuid) ON DELETE CASCADE,
  guid TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  author TEXT,
  content_html TEXT NOT NULL DEFAULT '',
  content_text TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  categories TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_inbox_source_guid ON library_inbox(source_uuid, guid);
CREATE INDEX ix_inbox_created ON library_inbox(created_at);
