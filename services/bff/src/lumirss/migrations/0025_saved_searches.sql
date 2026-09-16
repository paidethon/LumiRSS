-- 0025: Saved search views (pool #09).
--
-- Persists query + filter intent (NOT result sets): opening a view
-- re-runs the search, so new matching entries appear automatically.
-- params is a JSON object with whitelisted keys only (view, categoryKey)
-- — the server normalizes on write. Capped at 50 rows; over-limit
-- creates are rejected with a stable 409 (nothing is auto-evicted).

CREATE TABLE saved_searches (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  query TEXT NOT NULL,
  params TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX ix_saved_searches_created ON saved_searches(created_at);
