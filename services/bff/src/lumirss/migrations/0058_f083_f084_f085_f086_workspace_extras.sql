-- 0058: W5 workspace batch (F083 templates / F084 archive / F085 board /
-- F086 goals). All additive; existing workspaces keep working untouched.

-- F083 工作区模板：config_json 只携带非机密配置（描述/视图设置），
-- 绝不包含条目内容或凭据；example items 以 ref 引用（from-template 时
-- 才写 workspace_items），模板本体不复制内容。
CREATE TABLE workspace_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- F084 归档：NULL = 未归档；归档工作区默认导航隐藏、深链接仍可打开。
ALTER TABLE workspaces ADD COLUMN archived_at TEXT;

-- F085 看板：工作区内条目的三列状态（todo/reading/done）。独立于
-- FreshRSS 的 read/star（工作区进度是 Lumi 自有元数据）。
CREATE TABLE workspace_item_status (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    item_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('todo', 'reading', 'done')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, item_ref)
);

CREATE INDEX idx_workspace_item_status_status
    ON workspace_item_status (workspace_id, status);

-- F086 阅读目标：每工作区一个（PK）；进度 = 看板 done 去重条目数。
CREATE TABLE workspace_goals (
    workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    target_count INTEGER NOT NULL CHECK (target_count >= 1),
    deadline TEXT,
    created_at TEXT NOT NULL
);
