-- 0093: N144 saved searches gain retrieval scope.
--
-- workspace_id scopes a saved view to one workspace (nullable = no
-- workspace scope). The row does NOT reference workspaces(id) with a
-- FK ON DELETE: a deleted workspace must leave the saved view intact
-- but honestly flagged (scopeBroken, computed at read time) — the
-- reader decides to unlink, nothing is silently rewritten.
-- content_types_json stores the whitelisted content-type list (JSON
-- array; NULL = no content-type scope).

ALTER TABLE saved_searches ADD COLUMN workspace_id TEXT;
ALTER TABLE saved_searches ADD COLUMN content_types_json TEXT;
