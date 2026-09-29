-- 0178: NEW-252 假设登记册。
--
-- research_hypotheses：待检验的假设；创建时必须写下「可支持条件」与
-- 「可反驳条件」两栏（可反驳性是登记的最低门槛，缺一不发登记）。
-- status 由用户显式裁决：proposed（待检验）→ supported / refuted /
-- retired（撤回），绝无自动推断状态。
--
-- research_hypothesis_materials：阅读材料分配到假设的相应位置
-- （side='support' 可支持侧 / side='refute' 可反驳侧）；同一材料可以
-- 同时挂在两侧（用户自己判断），同一侧不重复。

CREATE TABLE IF NOT EXISTS research_hypotheses (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    support_condition TEXT NOT NULL,
    refute_condition TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'supported', 'refuted', 'retired')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_hypotheses_project
    ON research_hypotheses (project_id, created_at ASC);

CREATE TABLE IF NOT EXISTS research_hypothesis_materials (
    id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    side TEXT NOT NULL
        CHECK (side IN ('support', 'refute')),
    note TEXT,
    added_at TEXT NOT NULL,
    UNIQUE (hypothesis_id, item_ref, side)
);

CREATE INDEX IF NOT EXISTS idx_research_hypothesis_materials
    ON research_hypothesis_materials (hypothesis_id, side);
