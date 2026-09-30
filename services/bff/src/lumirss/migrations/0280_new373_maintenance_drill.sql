-- 0296: NEW-373 维护通知演练 —— 先演练、确认后再排程真实维护。
--
-- admin_maintenance_drills：演练记录（dry-run，绝不进入维护状态），
-- preview 列保存各角色将看到的通知渲染结果（与真实窗口共用同一
-- 渲染函数，演练即对现实的预演）。
--
-- admin_maintenance_windows：确认后的真实维护窗口（set 语义状态机
-- scheduled → completed/cancelled；行永不删除）。窗口在
-- [starts_at, ends_at) 区间内对全体用户经
-- GET /api/v1/maintenance/notice 如实可见——这是本表的唯一消费点，
-- 演练路径绝不写入本表。

CREATE TABLE IF NOT EXISTS admin_maintenance_drills (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    notice TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    preview TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_maintenance_windows (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    notice TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    settled_at TEXT,
    settled_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_maintenance_windows_starts
    ON admin_maintenance_windows(starts_at);
