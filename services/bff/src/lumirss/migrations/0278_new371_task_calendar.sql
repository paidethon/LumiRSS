-- 0294: NEW-371 后台任务日历 —— 管理员可见的实例周期任务治理面。
--
-- admin_task_runs：任务结果台账（kind + 状态 + 起止 + 脱敏 error）。
-- 写入者：治理路由与测试（结果聚合的既有真源仍是 F35 各域账本，
-- backup_jobs / gpt_digest_issues / digest_settings；本表只新增
-- 「调度器级」结果的统一落点，绝不含条目内容）。
--
-- admin_task_pauses：每类任务至多一条 active 暂停（含必填影响说明）。
-- 暂停是治理意图记录 + 真实消费点（main.py 内自有的两个循环在
-- 每次 tick 前检查；外部循环如 digest/RAG 的生效点属于其自身实现，
-- 日历以 enforcedBy 如实区分，绝不伪装成「已停止」）。

CREATE TABLE IF NOT EXISTS admin_task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    ref TEXT,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_task_runs_kind_time
    ON admin_task_runs(kind, started_at DESC);

CREATE TABLE IF NOT EXISTS admin_task_pauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    impact TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'lifted')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lifted_at TEXT,
    lifted_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_task_pauses_active
    ON admin_task_pauses(kind) WHERE status = 'active';
