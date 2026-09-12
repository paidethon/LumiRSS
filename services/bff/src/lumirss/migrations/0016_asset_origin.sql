-- 0016: persist the origin of snapshot assets (phase2 recovery P0-04).
-- library_assets stored only artifact metadata (path/bytes/sha256/mime),
-- so the original page URL was lost and list endpoints could only return
-- an empty url forever. Additive, forward-only: existing rows keep the
-- '' default (origin unknown — honest), new snapshots always record the
-- URL that was captured (already SSRF-validated at fetch time).
ALTER TABLE library_assets ADD COLUMN url TEXT NOT NULL DEFAULT '';
