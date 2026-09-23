-- 0070: P15 工作区续读指针 + 跨设备并发防护（每库一次）。
--
-- workspace_resume：每工作区一行（PK）「上次看到哪」指针。只存 ItemRef
-- 引用与保存时的位置快照，绝不复制内容（ADR 0004）；指向条目被移出
-- 工作区时由应用层清除（workspace_items 无反向 FK，见 workspaces.py）。
-- 工作区本身被删除时 FK 级联清掉指针行。
--
-- workspaces.revision：条目域变更计数器（add/remove/reorder/status 时
-- +1）。供重排序做 If-Match 式乐观并发：客户端带 expected_revision，
-- 不匹配 → 409（另一台设备已改动），客户端重取后重试；不带该参数的
-- 旧调用方行为不变。续读指针的 PUT 不 bump（它是每设备的阅读光标，
-- 不是共享条目状态——bump 会让正常阅读持续制造他人 409）。
ALTER TABLE workspaces ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;

CREATE TABLE workspace_resume (
    workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    item_ref TEXT NOT NULL,
    position_at_save INTEGER,
    updated_at TEXT NOT NULL
);
