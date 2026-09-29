-- 0145 (NEW-216): 集合快照差异 —— 资料集合（工作区）成员的命名快照。
-- 只存 ItemRef 引用列表（不复制内容，ADR 0004）；diff/恢复都是纯
-- 集合运算。工作区删除 → 快照行随 FK 级联消失。per-user 库。

CREATE TABLE IF NOT EXISTS new216_collection_snapshots (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    refs_json TEXT NOT NULL,
    ref_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_new216_snapshots_ws
  ON new216_collection_snapshots (workspace_id, created_at);
