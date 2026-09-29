-- 0182: NEW-256 研究决策记录。
--
-- research_decisions：个人决策行（基于哪些材料、作了什么决策）。
-- research_decision_materials：决策依据材料（ItemRef 只引用不复制）。
-- research_decision_followups：后续追加——kind='outcome' 结果 /
-- kind='revision' 修正原因。只追加，不更新不删除（追加台账，决策的
-- 演变过程全程可回看；本迁移到 0187 之间没有 followup 的 UPDATE 路径）。

CREATE TABLE IF NOT EXISTS research_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    basis TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_decisions_project
    ON research_decisions (project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS research_decision_materials (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (decision_id, item_ref)
);

CREATE TABLE IF NOT EXISTS research_decision_followups (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    kind TEXT NOT NULL
        CHECK (kind IN ('outcome', 'revision')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_decision_followups
    ON research_decision_followups (decision_id, created_at ASC);
