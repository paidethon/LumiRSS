-- 0180: NEW-254 研究术语表。
--
-- research_glossary_terms：项目内术语 → 本人采用的解释 + 出处。
-- UNIQUE(project_id, term)：同一项目里一个术语只有一个当前解释；
-- 改解释走 PATCH（旧解释不留历史——术语表是「当前采用」语义，与
-- NEW-259 结论历史「永不覆盖」的有意区别）。
--
-- 边界：本表是研究项目私有的工作术语表，与全局词典（glossary 表）
-- 完全无关——查词、改词都不触碰全局词典（不改动全局词典）。

CREATE TABLE IF NOT EXISTS research_glossary_terms (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    term TEXT NOT NULL,
    interpretation TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, term)
);

CREATE INDEX IF NOT EXISTS idx_research_glossary_terms_project
    ON research_glossary_terms (project_id, term ASC);
