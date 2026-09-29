-- 0262: NEW-339 共读模板 —— 把空间的栏目、角色规则和讨论模板保存为
-- **不含成员与内容**的模板；创建新空间时可先预览再应用。
--
-- 安全前提（测试断言）：模板行永远不携带成员清单或任何文章/讨论内容
-- ——栏目只存名称与顺序，角色规则只存开关，讨论模板是模板作者显式
-- 编写的引导文本。

CREATE TABLE IF NOT EXISTS space_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    source_space_id TEXT,
    sections_json TEXT NOT NULL DEFAULT '[]',
    role_rules_json TEXT NOT NULL DEFAULT '{}',
    discussion_templates_json TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    created_by_username TEXT NOT NULL,
    created_at TEXT NOT NULL
);
