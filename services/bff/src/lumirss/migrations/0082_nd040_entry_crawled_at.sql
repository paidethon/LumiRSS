-- 0075 (N040): FreshRSS crawl provenance on the projection row.
--
-- crawled_at = FreshRSS crawlTimestampMsec normalized to UTC Z (the moment
-- FreshRSS FIRST collected the entry — a real upstream timestamp, honestly
-- labeled as first-collection, never as a periodic fetch time). Enables the
-- three-timestamp latency block: 上游发布 / FreshRSS 收录 / Lumi 投影.

ALTER TABLE search_entries ADD COLUMN crawled_at TEXT;
