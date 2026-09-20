-- 0046: F042 API source pagination sampling.
--
-- api_sources gains a `pagination` config column (JSON):
--   {"mode":"none"|"page"|"cursor", "page_param"?, "first_page"?,
--    "cursor_path"?, "max_pages"?, "max_items"?}
-- mode "none" (default) keeps the single-shot fetch; "page" walks
-- ?page_param=N; "cursor" follows a JMESPath-extracted opaque cursor
-- appended as ?cursor=. Bounded by max_pages/max_items; mid-walk
-- upstream failures are atomic (nothing published for the run).
ALTER TABLE api_sources ADD COLUMN pagination TEXT NOT NULL DEFAULT '{"mode":"none"}';
