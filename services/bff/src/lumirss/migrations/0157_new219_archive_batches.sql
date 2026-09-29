-- 0148 (NEW-219): 文章批量归档 —— 本批收据（台账）。
-- refs_json = 实际归档成功的 refs；snapshots_json = 逐条归档前的
-- (read, starred) 状态快照（撤销时逐条比对「是否被后续修改」）。
-- undone_at 非空 = 已撤销（单向，重复撤销 409）。per-user 库。

CREATE TABLE IF NOT EXISTS new219_archive_batches (
    id TEXT PRIMARY KEY,
    refs_json TEXT NOT NULL,
    snapshots_json TEXT NOT NULL,
    archived_count INTEGER NOT NULL,
    failed_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    undone_at TEXT
);
