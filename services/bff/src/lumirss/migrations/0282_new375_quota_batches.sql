-- 0298: NEW-375 配额变更批次 —— 一组账户的额度变更先预览后执行，
-- 逐账户落结果（部分失败不回滚其他账户，结果如实分账）。

CREATE TABLE IF NOT EXISTS admin_quota_batches (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'executed', 'cancelled')),
    change TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    executed_at TEXT,
    executed_by TEXT
);

CREATE TABLE IF NOT EXISTS admin_quota_batch_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'skipped', 'error')),
    before_json TEXT,
    after_json TEXT,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_quota_batch_results_batch
    ON admin_quota_batch_results(batch_id, id);
