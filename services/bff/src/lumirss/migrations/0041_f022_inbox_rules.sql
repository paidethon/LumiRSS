-- 0041: F022 收件箱归类规则 —— ingest 成功建条目后应用第一条命中规则
-- 把条目归入目标工作区。
--
-- 只对新条目生效（不回溯改旧条目）；重复投递同 GUID 走 exists 路径，
-- 不重复触发副作用。priority 升序 = 应用顺序（第一条命中生效）。

CREATE TABLE IF NOT EXISTS inbox_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    priority INTEGER NOT NULL DEFAULT 0,
    field TEXT NOT NULL CHECK (field IN ('source', 'title')),
    operator TEXT NOT NULL CHECK (operator IN ('contains', 'equals')),
    value TEXT NOT NULL,
    target_workspace_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inbox_rules_priority ON inbox_rules (priority, id);
