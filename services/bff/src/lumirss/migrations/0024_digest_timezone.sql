-- 0024: Digest send timezone (pool #31).
--
-- ``hour`` used to be interpreted in the SERVER's local timezone — a
-- deployment move silently shifts when digests go out. The new column
-- holds an IANA timezone name ('' = server local, the documented
-- pre-0024 behavior, so existing rows keep their semantics).

ALTER TABLE digest_settings ADD COLUMN timezone TEXT NOT NULL DEFAULT '';
