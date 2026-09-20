-- 0052: F062 译文手工纠错与保护。
--
-- ai_translation_segments 每段增加：
-- - user_revision：用户手工修订文本（NULL = 未修订）；
-- - revised_at：修订保存时间；
-- - source_hash：保存修订时的源段 hash（= 当时行的 block_hash）。
--
-- 修订以 (entry_ref, block_index) 为语义单位，写入该段当前全部缓存
-- 变体（不同源文/引擎/模型/语言各成一行的缓存身份），因此：
-- - 重新生成同源段（ON CONFLICT 更新）不动修订列；
-- - 源文变化产生新 hash 行后，修订仍按 index 关联并比对 source_hash
--   != block_hash 标记 stale（保留不误删）。
-- 管理端 API 永不把这三个列之外的内容当作机器译文返回。

ALTER TABLE ai_translation_segments ADD COLUMN user_revision TEXT;
ALTER TABLE ai_translation_segments ADD COLUMN revised_at TEXT;
ALTER TABLE ai_translation_segments ADD COLUMN source_hash TEXT;
