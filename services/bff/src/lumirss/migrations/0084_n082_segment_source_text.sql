-- 0084: N082 翻译数字校验 —— 段缓存行补充源段文本。
--
-- ai_translation_segments 增加 source_text（normalize 后的源段文本）。
-- 此前该表只存 block_hash（源文本的 SHA-256），数字校验需要源/译两侧
-- 的可见文本才能逐块比对；source_text 由生成/更新写入，身份键含
-- block_hash，正文改版即产生新行，陈旧源文本永远不会被当作当前内容
-- 使用。迁移前的旧行该列为 NULL → 校验端点对这些块诚实返回
-- source_text_unavailable（绝不猜）。

ALTER TABLE ai_translation_segments ADD COLUMN source_text TEXT;
