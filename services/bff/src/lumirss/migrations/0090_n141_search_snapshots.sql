-- 0092: N141 search result snapshots.
--
-- A snapshot freezes the RESULT REFS of one query+filter scope at
-- freeze time (bounded keyset walk, cap 2000 refs, honest truncation
-- flag inside filters_json) so it can later be compared against a
-- re-run of the same scope. Per-user table (RoutingDatabase routes by
-- request identity); capped at 20 rows per user — an over-limit create
-- prunes the OLDEST rows inside the insert transaction (explicit
-- DELETE, no silent evictions beyond the documented cap).

CREATE TABLE search_snapshots (
  id TEXT PRIMARY KEY,
  query TEXT NOT NULL,
  filters_json TEXT NOT NULL,
  ref_list_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX ix_search_snapshots_created ON search_snapshots(created_at);
