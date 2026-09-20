-- 0059: F089 剪藏手工修订 + F090 笔记全生命周期（均为加列，前向兼容）。

-- F089：原始 content_html 永不覆盖——修订结果存独立列；
-- base_content_hash = 修订时所见版本的 hash（乐观并发，409 base_mismatch）。
ALTER TABLE library_clips ADD COLUMN revised_content_html TEXT;
ALTER TABLE library_clips ADD COLUMN revised_note TEXT;
ALTER TABLE library_clips ADD COLUMN revised_at TEXT;
ALTER TABLE library_clips ADD COLUMN base_content_hash TEXT;

-- F090：笔记软删（回收站 kind=note）；NULL = 存活。
ALTER TABLE lumi_notes ADD COLUMN deleted_at TEXT;

CREATE INDEX idx_lumi_notes_deleted ON lumi_notes (deleted_at);
