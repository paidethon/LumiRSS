-- 0254: NEW-331..340 共读空间的协作秩序 —— 最小显式共享基底（控制库）。
--
-- 隐私前提（硬规则）：本组一切共享内容都走**显式动作**（管理者显式
-- 添加成员、成员显式投稿/共享），私人阅读状态绝不自动进入空间视图。
-- 控制库承载跨用户行（与 NEW-236 批注共享串 / NEW-229 控制面同一
-- 先例——跨用户是控制关注点）；迁移集仍同时应用于控制库与每个
-- per-user 库，但这些表只在控制库使用。
--
-- space_spaces：空间本身（owner_user_id = 空间管理者/创建者）；
--   require_approval = NEW-332 投稿审批开关；archived_at = NEW-340
--   归档只读；discussion_templates_json = NEW-339 讨论模板随空间落
--   地（纯模板文本，不含成员与内容）。
-- space_members：显式成员（管理者行永不过期；成员行 expires_at 为
--   NEW-334 权限到期——到期只撤销空间权限，绝不触碰个人账户）；
--   revoked_at = 管理者移除或成员自行退出。
-- space_sections：空间栏目（NEW-339 模板的快照来源；纯结构，无内容）。

CREATE TABLE IF NOT EXISTS space_spaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner_user_id TEXT NOT NULL,
    require_approval INTEGER NOT NULL DEFAULT 0,
    discussion_templates_json TEXT NOT NULL DEFAULT '[]',
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_members (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    expires_at TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (space_id, user_id)
);

CREATE TABLE IF NOT EXISTS space_sections (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (space_id, name)
);

CREATE INDEX IF NOT EXISTS idx_space_members_user
    ON space_members (user_id, space_id);

CREATE INDEX IF NOT EXISTS idx_space_sections_space
    ON space_sections (space_id, position ASC);
