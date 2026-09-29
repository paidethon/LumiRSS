-- 0185: NEW-259 结论变更记录。
--
-- research_conclusions：项目当前结论（每项目一行）。
-- research_conclusion_history：变更台账——每次修改都整行记录
-- old_text（原结论）、new_text（新表述）、trigger_refs（触发材料，
-- JSON 数组）、reason。只追加，永不更新/删除：回看历史时看到的都是
-- 当时如实登记的内容（诚实边界：本组核心要求「保留原结论，不覆盖」）。
-- 首次登记结论也进台账（old_text 为 NULL，诚实表示「此前未登记」）。

CREATE TABLE IF NOT EXISTS research_conclusions (
    project_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_conclusion_history (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    old_text TEXT,
    new_text TEXT NOT NULL,
    trigger_refs TEXT NOT NULL DEFAULT '[]',
    reason TEXT,
    changed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_conclusion_history
    ON research_conclusion_history (project_id, changed_at DESC);
