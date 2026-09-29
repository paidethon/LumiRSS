-- 0177: NEW-251 研究问题拆分 + 研究项目主线（research_projects）。
--
-- research_projects：本组（NEW-251..260）共用的项目主线。项目只是
-- 本人库里的分组锚点（per-user 库天然隔离）；不做共享、不做协作。
--
-- research_questions：研究项目下的父问题（把一个阅读问题正式立项）。
-- 与 N074 reading_questions（随手记的阅读问题清单）互补：这里的问题
-- 属于某个研究项目、要被拆解。
--
-- research_subquestions：子问题——每个子问题有自己的结论草稿与
-- unresolved/resolved 状态（status 只有两态，set 语义切换）。
--
-- research_question_materials：子问题 ↔ 材料的关联（ItemRef 只引用
-- 不复制，ADR 0004；同一材料在同一子问题下唯一）。

CREATE TABLE IF NOT EXISTS research_projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_questions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    question TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_questions_project
    ON research_questions (project_id, created_at ASC);

CREATE TABLE IF NOT EXISTS research_subquestions (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    text TEXT NOT NULL,
    conclusion TEXT,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_subquestions_question
    ON research_subquestions (question_id, created_at ASC);

CREATE TABLE IF NOT EXISTS research_question_materials (
    id TEXT PRIMARY KEY,
    subquestion_id TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (subquestion_id, item_ref)
);
