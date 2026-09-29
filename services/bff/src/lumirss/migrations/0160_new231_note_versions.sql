-- 0142: NEW-231 笔记修订对照 —— 显式版本快照 + 恢复记录。
--
-- note_versions：一条笔记的显式版本快照（origin='manual' 用户手动快照 /
-- origin='pre_restore' 恢复前自动快照）。旧版内容完整保留，恢复绝不
-- 覆盖历史——恢复前先把当前版推入本表。
--
-- note_restore_log：恢复动作台账（恢复记录）：恢复了哪个版本、恢复时
-- 的最新版本号、恢复时间。只追加，不删除。
--
-- 与 0132 lumi_note_revisions（仅 ai_answer 证据笔记的血统链）互补：
-- 本表服务全部笔记的显式版本管理与恢复。

CREATE TABLE IF NOT EXISTS note_versions (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_note_versions_note
    ON note_versions (note_id, created_at DESC);

CREATE TABLE IF NOT EXISTS note_restore_log (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    version_origin TEXT NOT NULL,
    restored_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_note_restore_log_note
    ON note_restore_log (note_id, restored_at DESC);
