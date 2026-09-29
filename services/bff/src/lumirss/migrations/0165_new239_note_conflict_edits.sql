-- 0147: NEW-239 标注冲突解决器 —— 笔记版本列 + 待决冲突编辑。
--
-- lumi_notes.version：单调递增整数（创建 = 1，每次经 NEW-239 通道
-- 成功写入 +1）。冲突检测 = 客户端提交的 baseVersion ≠ 当前 version。
--
-- note_pending_edits：冲突时另一台设备的编辑暂存（永不丢弃——
-- 409 的编辑进本表等待并排解决）。status: pending / resolved。
-- note_conflict_log：解决台账（keep_server / keep_pending /
-- keep_both / merged + 解决时间）。keep_pending/merged 时被覆盖的
-- 服务端版先入 note_versions（origin='conflict'），历史不覆盖。

ALTER TABLE lumi_notes ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS note_pending_edits (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    device_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    resolution TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_note_pending_edits
    ON note_pending_edits (note_id, created_at DESC);

CREATE TABLE IF NOT EXISTS note_conflict_log (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    pending_edit_id TEXT NOT NULL,
    resolution TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);
