-- 0099: N113 分节大纲（每库一次）。
--
-- workspace_sections：工作区内的显式分节（有标题、有顺序），与 N101
-- 隐式分组互补——分组是呈现层派生的标签，分节是用户显式创建的大纲
-- 结构（汇编预览 N114 的输入）。
--
-- workspace_section_items：分节成员。条目以 item_ref 引用（与
-- workspace_items.item_ref 同构），绝不复制内容（ADR 0004）；同一
-- article 可同时出现在多个分节（PK 是 (section_id, item_ref)，跨分节
-- 只有引用、没有第二份内容）。position 是节内顺序（追加 = 尾部，
-- 重排持久化）；工作区内条目被移除后分节引用行保留、由列表端点诚实
-- 标记 unresolved（清理预演 N120 可显式移除，绝不静默）。
--
-- 工作区删除 → FK 级联清掉分节与分节引用（与 workspace_snapshots 同
-- 模式）；分节删除 → 分节引用行随 FK 级联消失。

CREATE TABLE workspace_sections (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    sort_index INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_workspace_sections_order
    ON workspace_sections (workspace_id, sort_index);

CREATE TABLE workspace_section_items (
    section_id TEXT NOT NULL REFERENCES workspace_sections(id) ON DELETE CASCADE,
    item_ref TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL,
    PRIMARY KEY (section_id, item_ref)
);

CREATE INDEX ix_workspace_section_items_order
    ON workspace_section_items (section_id, position);
