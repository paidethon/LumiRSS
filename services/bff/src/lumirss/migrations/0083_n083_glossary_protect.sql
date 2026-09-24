-- 0083: N083 专有名词保留清单。
--
-- glossary_terms 增加 protect 标记（0/1）：protect=1 的术语在分段翻译
-- 生成后做还原后处理（译文里大小写漂移的术语恢复为词表原始词形；
-- 完全缺失则如实上报「未保护」，绝不臆造）。
--
-- 缓存失效：ai_translation_segments 的缓存身份加入 glossary_version
-- 列（glossary_meta 表持久的单调版本号；任何术语写操作 +1）。初始值
-- 为空串 —— 与既有缓存行的默认值一致，因此只在第一次术语写入后才
-- 自然失效（「只有受 glossary 影响的缓存改变」）；此前的旧行因版本号
-- 推进而天然不再匹配，绝不回填陈旧译文。

ALTER TABLE glossary_terms ADD COLUMN protect INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS glossary_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO glossary_meta (key, value) VALUES ('glossary_version', '');

ALTER TABLE ai_translation_segments ADD COLUMN glossary_version TEXT NOT NULL DEFAULT '';

DROP INDEX ai_translation_segments_identity;

CREATE UNIQUE INDEX ai_translation_segments_identity ON ai_translation_segments (
    entry_ref, block_index, block_hash, provider, model, prompt_version,
    target_language, glossary_version
);
