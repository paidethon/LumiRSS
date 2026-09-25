-- 0100: N120 工作区清理预演（每库一次）。
--
-- workspace_cleanup_log：apply 前的快照日志（N105 会话快照同构：
-- payload_json 只携带被移除行的完整原值 + 移除前的组顺序，绝不复制
-- 内容）。POST /cleanup 每次真实删除前先写一条；上限 5 条（超出淘汰
-- 最旧），POST /cleanup/undo 按日志恢复被移除的行。日志只服务撤销：
-- 工作区删除 → 行随 FK 级联消失（撤销历史随之失效，工作区都没了）。
--
-- 清理契约（写在这里，代码与测试共同守护）：
-- - 只移除 Lumi 自有元数据行（stale workspace_items 成员行 / 空组名 /
--   悬空 workspace_section_items 引用）；
-- - 绝不触碰 FreshRSS 数据（read/star/条目本体）；
-- - 绝不移除 library: 域引用（库对象受保护，即使已解析不到）。

CREATE TABLE workspace_cleanup_log (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX ix_workspace_cleanup_log_workspace
    ON workspace_cleanup_log (workspace_id, created_at);
