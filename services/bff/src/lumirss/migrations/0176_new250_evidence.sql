-- 0176: NEW-250 证据完整性检查单 —— 报告引文证据项。
--
-- evidence_items：一份个人报告（report_label）里每条引文的证据记录：
-- source_ref（来源指向）、version_id（保存版本指向 NEW-241 的
-- article_saved_versions.id）、excerpt（可定位片段）。三项状态在查询
-- 时计算（显式记录为准，另参考 citation_edges / article_saved_versions
-- 的既有事实），缺项由用户逐个补齐（PATCH 单项），系统不代填。

CREATE TABLE IF NOT EXISTS evidence_items (
    id TEXT PRIMARY KEY,
    report_label TEXT NOT NULL,
    citation_ref TEXT NOT NULL,
    source_ref TEXT,
    version_id TEXT,
    excerpt TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (report_label, citation_ref)
);

CREATE INDEX IF NOT EXISTS idx_evidence_items_report
    ON evidence_items (report_label, citation_ref);
