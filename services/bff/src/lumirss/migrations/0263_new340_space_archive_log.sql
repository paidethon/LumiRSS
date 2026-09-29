-- 0263: NEW-340 空间归档流程 —— 归档前列出未完成任务并由管理者处理
-- （或显式 force 确认跳过）；归档后空间只读（一切写操作 409）；恢复
-- 时管理者必须逐成员重新确认权限（未列入 keep 清单的成员被撤销）。
-- 本表记录归档/恢复动作与当时的任务快照，便于回看。

CREATE TABLE IF NOT EXISTS space_archive_log (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    tasks_json TEXT NOT NULL DEFAULT '[]',
    kept_members_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_space_archive_log_space
    ON space_archive_log (space_id, created_at DESC);
