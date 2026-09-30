-- 0312: NEW-389 分卷导出卷集与导入台账。
--
-- 卷集：每卷容量上限、卷数、逐卷清单（条目 id + 卷内 sha256）。
-- 导入：收到的卷清单、缺失卷判定（缺卷 → 拒绝导入，绝不默默少导）、
-- 完整导入时的 added / matched / failed 计数（逐条结果交给 NEW-390 对账）。

CREATE TABLE IF NOT EXISTS new389_volume_sets (
    id TEXT PRIMARY KEY,
    volume_count INTEGER NOT NULL DEFAULT 0,
    max_volume_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    volumes_json TEXT NOT NULL DEFAULT '[]',
    item_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS new389_volume_imports (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('incomplete', 'imported')),
    received_volumes INTEGER NOT NULL DEFAULT 0,
    expected_volumes INTEGER NOT NULL DEFAULT 0,
    missing_json TEXT NOT NULL DEFAULT '[]',
    added INTEGER NOT NULL DEFAULT 0,
    matched INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    reconciliation_id TEXT,
    created_at TEXT NOT NULL
);
