-- 0011: Mail/newsletter bridge + digest (phase2 G5). Bridge state and
-- digest config are Lumi-owned; converted newsletter entries live ONLY
-- in FreshRSS via the per-list Atom (no second article database).
CREATE TABLE mail_bridge_lists (
  uuid TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  secret TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE mail_seen (
  message_id TEXT PRIMARY KEY,
  list_uuid TEXT NOT NULL,
  seen_at TEXT NOT NULL
);

CREATE INDEX ix_mail_seen_list ON mail_seen(list_uuid, seen_at);

CREATE TABLE mail_bridge_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  list_uuid TEXT NOT NULL,
  message_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  sender TEXT NOT NULL DEFAULT '',
  html TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL DEFAULT '',
  attachment_count INTEGER NOT NULL DEFAULT 0,
  attachment_meta TEXT NOT NULL DEFAULT '[]',
  received_at TEXT NOT NULL
);

CREATE INDEX ix_mail_entries_list ON mail_bridge_entries(list_uuid, received_at);

CREATE TABLE mail_bridge_atoms (
  uuid TEXT PRIMARY KEY,
  list_uuid TEXT NOT NULL REFERENCES mail_bridge_lists(uuid) ON DELETE CASCADE,
  secret TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE digest_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  enabled INTEGER NOT NULL DEFAULT 0,
  hour INTEGER NOT NULL DEFAULT 8,
  source TEXT NOT NULL DEFAULT 'read_later',
  limit_count INTEGER NOT NULL DEFAULT 10,
  smtp_host TEXT NOT NULL DEFAULT '',
  smtp_port INTEGER NOT NULL DEFAULT 587,
  smtp_user TEXT NOT NULL DEFAULT '',
  from_addr TEXT NOT NULL DEFAULT '',
  to_addr TEXT NOT NULL DEFAULT '',
  last_sent_at TEXT,
  last_error TEXT
);

INSERT INTO digest_settings (id, enabled, hour, source, limit_count, smtp_host, smtp_port, smtp_user, from_addr, to_addr)
VALUES (1, 0, 8, 'read_later', 10, '', 587, '', '', '');
