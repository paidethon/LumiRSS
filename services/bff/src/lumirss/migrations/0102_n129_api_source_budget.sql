-- 0104: N129 API 限额友好策略.
--
-- api_sources gains a per-source fetch budget:
--   max_runs_per_hour   — token-bucket capacity for the FreshRSS-facing
--                         Atom fetch path (default 4/hour);
--   respect_retry_after — FIXED true (column kept so the policy is
--                         explicit in the schema; never written to 0);
--   next_allowed_run    — RFC3339 timestamp set when the upstream
--                         answered 429 with Retry-After (or when the
--                         local bucket is exhausted).
-- api_source_runs is the persisted token bucket (one row per upstream
-- run; pruned to the trailing hour on every consult).
ALTER TABLE api_sources ADD COLUMN max_runs_per_hour INTEGER NOT NULL DEFAULT 4;
ALTER TABLE api_sources ADD COLUMN respect_retry_after INTEGER NOT NULL DEFAULT 1;
ALTER TABLE api_sources ADD COLUMN next_allowed_run TEXT;

CREATE TABLE api_source_runs (
  source_uuid TEXT NOT NULL,
  ran_at TEXT NOT NULL
);

CREATE INDEX ix_api_source_runs_source_time ON api_source_runs(source_uuid, ran_at);
