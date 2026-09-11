-- 0008: Library domain foundation (phase2 M1).
--
-- library_items is the canonical identity table for every Lumi-owned
-- content object: workspace/tag/rag references point at library:<uuid>
-- and never at kind-specific rows. Kind-specific payloads live in their
-- own tables (library_bookmarks below; clips/snapshots/notes in later
-- migrations). RSS entries are NEVER copied here — rss: refs stay in
-- FreshRSS ownership.
CREATE TABLE library_items (
  uuid TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (
    kind IN ('bookmark', 'clip', 'snapshot', 'api_item', 'newsletter_item', 'obsidian_note')
  ),
  created_at TEXT NOT NULL
);

CREATE INDEX ix_library_items_kind ON library_items(kind, created_at);

CREATE TABLE library_bookmarks (
  item_uuid TEXT PRIMARY KEY REFERENCES library_items(uuid) ON DELETE CASCADE,
  item_type TEXT NOT NULL CHECK (item_type IN ('url', 'rss')),
  url TEXT,
  rss_item_ref TEXT,
  title TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  CHECK ((item_type = 'url') = (url IS NOT NULL)),
  CHECK ((item_type = 'rss') = (rss_item_ref IS NOT NULL))
);

CREATE UNIQUE INDEX ux_bookmarks_url
  ON library_bookmarks(url) WHERE url IS NOT NULL;
CREATE INDEX ix_bookmarks_rss_ref
  ON library_bookmarks(rss_item_ref) WHERE rss_item_ref IS NOT NULL;

-- Workspaces: ordered collections of typed ItemRefs. Content is never
-- copied — a workspace row is only (workspace, ref, position).
CREATE TABLE workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE workspace_items (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  item_ref TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  added_at TEXT NOT NULL,
  UNIQUE (workspace_id, item_ref)
);

CREATE INDEX ix_workspace_items_order ON workspace_items(workspace_id, position);

-- The reserved read-later workspace is a permanent seed row: the API
-- refuses to delete or rename it (reserved_workspace_id), so readers can
-- treat it as the "reading queue" anchor.
INSERT INTO workspaces (id, name, position, created_at)
VALUES ('read-later', '稍后读', 0, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));
