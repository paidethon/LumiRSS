-- 0188: NEW-261 术语表冲突处理 —— 同名多义术语的生效译法选择。
--
-- glossary_terms 天然允许同一 term 多条词目（同词不同含义并存）。
-- 冲突场景下「哪条译法生效」此前由列表顺序偶然决定（不诚实）；
-- 本表记录用户为某术语显式选择的生效译法：
--
-- - scope='project'：全项目生效（source_url=''）；
-- - scope='source'：仅对某来源生效（source_url=feed url）；
-- - 解析优先级：来源选择 > 项目选择 > 默认（updated_at 最新一条）。
--
-- 写入/清除选择都会推进 glossary_version（分段翻译缓存身份的组成
-- 部分）：已产生的译文缓存行保持原身份、原样展示（不悄悄改变），
-- 其后的新生成按生效译法出稿。

CREATE TABLE IF NOT EXISTS glossary_term_choices (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL,
    chosen_term_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('project', 'source')),
    source_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (term, scope, source_url)
);

CREATE INDEX IF NOT EXISTS idx_glossary_term_choices_term
    ON glossary_term_choices (term, scope, source_url);
