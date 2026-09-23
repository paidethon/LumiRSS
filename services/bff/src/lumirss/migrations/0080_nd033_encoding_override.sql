-- 0073 (N033): per-source decoding override (encoding diagnostics).
--
-- encoding_override ∈ 'utf-8' | 'declared' | 'detected' — the user's
-- explicit choice from the reparse diagnostics. It applies to LumiRSS's
-- OWN feed-bytes → text decode point (feed preview / reparse) and only to
-- FUTURE fetches: already-projected history is never rewritten silently.

ALTER TABLE source_overrides ADD COLUMN encoding_override TEXT;
