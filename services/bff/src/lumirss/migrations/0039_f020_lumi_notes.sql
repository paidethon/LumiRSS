-- 0039: F020 本地 Markdown 批量入库 —— Lumi 自有笔记实体（最小实体）。
--
-- 本波次只做入库与列表（F090 编辑/关联/删除恢复在后续波次补全）。
-- content_hash 用于幂等导入（同内容 → skipped）；source 标记来源
-- （import=批量导入 | manual=手动创建，后续波次使用）。
-- workspace_id 可空（未分组）；不做 FK 级联（工作区删除不级联笔记）。

CREATE TABLE IF NOT EXISTS lumi_notes (
    uuid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    workspace_id TEXT,
    content_hash TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lumi_notes_workspace ON lumi_notes (workspace_id);
CREATE INDEX IF NOT EXISTS idx_lumi_notes_hash ON lumi_notes (content_hash);
