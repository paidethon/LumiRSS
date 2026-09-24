-- 0084: N105 工作区会话快照（每库一次）。
--
-- workspace_snapshots：工作区标签页/分组状态的命名快照。payload_json
-- 只携带 ItemRef 引用与排序元数据（{items:[{item_ref, group, pinned,
-- position}], group_order}），绝不复制内容（ADR 0004：解析在读取时经
-- Source Registry 完成）。恢复时只对仍存在的成员重排/重分组/重固定，
-- 消失的 ref 诚实上报、绝不复活。
--
-- 工作区被删除时 FK 级联清掉快照行（与 workspace_resume 同模式）。

CREATE TABLE workspace_snapshots (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX ix_workspace_snapshots_workspace
  ON workspace_snapshots(workspace_id, created_at);
