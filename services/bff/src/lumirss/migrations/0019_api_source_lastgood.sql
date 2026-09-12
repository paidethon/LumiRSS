-- 0019: API source last-known-good Atom (phase2 recovery P0-05d/e,
-- IMPL-BE-2).
--
-- Problem: the Atom body was regenerated per request and never
-- persisted, so an upstream failure had nothing to serve (502 stub)
-- and feed updated/ETag were wall-clock unstable.
--
-- New columns on api_sources:
--   atom_body    — last successfully fetched+mapped rendered Atom
--                  document (served stale with X-Lumi-Stale when the
--                  upstream is down; rebuildable artifact, NOT a
--                  second content database — bounded by the 100-item
--                  feed cap);
--   feed_updated — persisted, monotonic, content-derived feed
--                  timestamp (newest entry updated clamped against the
--                  previous value) so ETags are stable across fetches
--                  and 304s are reliable.
ALTER TABLE api_sources ADD COLUMN atom_body TEXT;

ALTER TABLE api_sources ADD COLUMN feed_updated TEXT;
