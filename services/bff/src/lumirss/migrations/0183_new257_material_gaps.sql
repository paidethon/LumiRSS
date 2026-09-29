-- 0183: NEW-257 资料缺口任务。
--
-- research_material_gaps：某份研究需要但尚未找到的资料类型/描述。
-- status 只有 open | closed 两态：
--   - close 是显式动作：必须挂上找到的材料（closed_item_ref），
--     可留 close_note；
--   - reopen 留 reopen 后可再次关闭（closed_at 记最后一次关闭）；
--   - 已关闭再 close → 422（诚实拒绝，不做幂等假成功）。

CREATE TABLE IF NOT EXISTS research_material_gaps (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    description TEXT NOT NULL,
    material_type TEXT,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    closed_item_ref TEXT,
    close_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_material_gaps_project
    ON research_material_gaps (project_id, status, created_at ASC);
