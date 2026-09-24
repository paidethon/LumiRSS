-- 0083: N101 标签页分组 + N102 固定标签页（每库一次，全部增量列）。
--
-- N101 分组：workspace_items.group_name 是可选组标签（NULL = 未分组，
-- 呈现时是「隐式前置组」）。设计取舍（有意不用 workspace_groups 表）：
-- 组的成员关系完全由 workspace_items.group_name 派生（行按 workspace_id
-- 隔离，跨工作区串扰在结构上不可能）；组的顺序存 workspaces.group_order_json
-- （组名有序数组）——组顺序只是呈现顺序提示，单独一张表会引入「组内最后
-- 一条被移走后孤儿行」的 GC 问题，而 JSON 列与 workspace_templates 的
-- config_json 同构。组内顺序沿用既有 position（重排序契约不变）。
--
-- N102 固定：workspace_items.pinned（0/1）。固定条目在分组视图中排在
-- 所有组之前（仍按 position 排序）；移除固定条目需显式 force=1
--（409 workspace_item_pinned），恢复快照 replace 模式同样受保护。

ALTER TABLE workspace_items ADD COLUMN group_name TEXT;

ALTER TABLE workspace_items ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;

ALTER TABLE workspaces ADD COLUMN group_order_json TEXT NOT NULL DEFAULT '[]';

CREATE INDEX ix_workspace_items_group
  ON workspace_items(workspace_id, group_name);
