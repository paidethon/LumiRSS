-- 0194: NEW-269 语言识别纠正 —— 用户更正某文/某源的识别语言。
--
-- scope='entry'：ref_key=entry_ref（单篇更正）；
-- scope='source'：ref_key=feed_url（整源更正，单篇更正优先）。
-- 每对 (scope, ref_key) 至多一条（再次更正即覆盖，保留首次
-- created_at）。
--
-- 语义（已产生结果不悄悄改变）：更正只影响其后的新生成
-- （LibreTranslate 的 source 参数 / AI 引擎的源语言指令）；既有
-- 缓存译文原样展示。缓存身份不变 —— 旧结果不会因更正而失效或
-- 被改写。

CREATE TABLE IF NOT EXISTS translation_language_overrides (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('entry', 'source')),
    ref_key TEXT NOT NULL,
    language TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (scope, ref_key)
);

CREATE INDEX IF NOT EXISTS idx_translation_language_overrides_ref
    ON translation_language_overrides (scope, ref_key);
