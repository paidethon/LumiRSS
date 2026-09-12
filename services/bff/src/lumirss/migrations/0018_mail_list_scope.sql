-- 0018: mail_seen per-list scope + stable identity (phase2 recovery
-- P0-06e/k, IMPL-BE-2).
--
-- Problem: mail_seen.message_id was a GLOBAL primary key, so the same
-- newsletter delivered to two bridge lists collided — the second list's
-- delivery was wrongly reported duplicate and silently dropped. The
-- fallback identity also mixed second-resolution utc_now() into the
-- fingerprint, making re-delivery dedupe nondeterministic across second
-- boundaries.
--
-- Forward-only rebuild as a composite-key dedupe cache named mail_seen:
-- 1. create mail_seen_v2 with PRIMARY KEY (list_uuid, identity);
-- 2. copy all old rows (old (message_id, list_uuid) maps 1:1;
--    duplicates are impossible under the old global PK);
-- 3. drop the old table and rename v2 into its place.
--
-- Dropping the old table is SAFE: mail_seen is a dedupe CACHE, not
-- content. A lost/cold row can only cause one redundant ingest of an
-- already-delivered mail (the entry body lives in mail_bridge_entries);
-- identities for old-style fingerprint rows never match the new content
-- fingerprint and are inert. No entry data is read from or written to
-- the old table.
CREATE TABLE mail_seen_v2 (
  list_uuid TEXT NOT NULL,
  identity TEXT NOT NULL,
  seen_at TEXT NOT NULL,
  PRIMARY KEY (list_uuid, identity)
);

INSERT INTO mail_seen_v2 (list_uuid, identity, seen_at)
  SELECT list_uuid, message_id, seen_at FROM mail_seen;

DROP TABLE mail_seen;

ALTER TABLE mail_seen_v2 RENAME TO mail_seen;
