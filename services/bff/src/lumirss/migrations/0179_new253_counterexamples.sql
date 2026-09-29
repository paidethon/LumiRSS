-- 0179: NEW-253 反例收集视图。
--
-- research_counterexamples：与现有结论相冲突的原文证据单独立项收集。
-- excerpt 必填（原文摘录）；item_ref 可选（来源后补——证据先记下、
-- 出处后补与 N074 同一惯例）。
--
-- 处理是显式用户动作：resolve 时必须回答「结论是否调整」
-- （conclusion_adjusted 0/1）并留 resolution_note；未处理的行
-- status='unhandled'。是否真的调整结论由用户去 NEW-259 结论变更记录
-- 完成——本表只记账「反例被处理过、处理时怎么说的」，绝不替用户改结论。

CREATE TABLE IF NOT EXISTS research_counterexamples (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    item_ref TEXT,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'unhandled'
        CHECK (status IN ('unhandled', 'handled')),
    resolution_note TEXT,
    conclusion_adjusted INTEGER,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_counterexamples_project
    ON research_counterexamples (project_id, created_at DESC);
