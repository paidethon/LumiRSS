-- 0146 (NEW-217): 集合排序配方 —— 为指定集合保存多字段排序与固定例外。
-- fields_json 形如 [{"key":"title","dir":"asc"}, ...]；exceptions_json
-- 是保持原位的 ItemRef 列表。配方只属于一个集合，其他列表不受影响。
-- 工作区删除 → 配方行随 FK 级联消失。per-user 库。

CREATE TABLE IF NOT EXISTS new217_sort_recipes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    exceptions_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_new217_recipes_ws
  ON new217_sort_recipes (workspace_id, created_at);
