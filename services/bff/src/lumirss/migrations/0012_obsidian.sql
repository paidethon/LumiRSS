-- 0012: Obsidian read-only vault projection (phase2 G6) + library favorites.
-- The Vault is the source of truth; every row here is derived,
-- rebuildable from a full rescan, and Lumi NEVER writes to the vault.
CREATE TABLE obsidian_notes (
  item_uuid TEXT PRIMARY KEY REFERENCES library_items(uuid) ON DELETE CASCADE,
  rel_path TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  title TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  wikilinks TEXT NOT NULL DEFAULT '[]',
  body_text TEXT NOT NULL DEFAULT '',
  indexed_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_obsidian_relpath ON obsidian_notes(rel_path);
CREATE INDEX ix_obsidian_fingerprint ON obsidian_notes(content_hash);

CREATE TABLE library_favorites (
  ref TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

CREATE TABLE obsidian_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  vault_path TEXT NOT NULL DEFAULT '',
  last_scan_at TEXT,
  last_error TEXT
);

INSERT INTO obsidian_settings (id, vault_path) VALUES (1, '');
