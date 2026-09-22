-- 0067: 邀请制多账户（O145/O146/O149/O151/O155）。
--
-- 本库（LUMIRSS_DB_PATH）升级为「控制库」：只存身份、会话、邀请、
-- FreshRSS 供应池与审计。各用户的业务数据（订阅投影、资料库、AI、
-- 任务……）在各自 users/<uid>/lumi.sqlite，由 user_scope 按认证身份
-- 打开——业务表在本库永远为空（旧单用户库的数据在 owner 迁移时
-- 物理移动到 owner 用户库，见 owner_migration.py）。
--
-- 密码哈希沿用 bcrypt（auth_store 同一算法与成本）；会话仍存
-- SHA-256(token)，新增 user_id 绑定。邀请只存 SHA-256(token)——
-- 原始 token 仅在创建响应中出现一次。

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    display_name TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    password_updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS invites (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'signup' CHECK (kind IN ('signup', 'recovery')),
    target_user TEXT,
    label TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    used_by TEXT,
    revoked_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_invites_expires ON invites(expires_at);

-- FreshRSS 供应池（O155）：运营者用受支持的部署侧 CLI 预建空用户，
-- 登记后供邀请激活原子分配。API 密码不进 SQLite——存控制层
-- secrets.json（0600，键 freshrss_pool:<username>，AD-0018-6 同一
-- 决策）。BFF 不挂 Docker socket、不执行 shell——池由
-- scripts/freshrss_pool.py 或管理员 API 逐条登记。
CREATE TABLE IF NOT EXISTS freshrss_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    freshrss_username TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'ready' CHECK (state IN ('ready', 'assigned')),
    assigned_user TEXT,
    assigned_at INTEGER,
    created_at INTEGER NOT NULL
);

-- F038/O172：最小审计（操作者、对象、结果；不含正文/凭据）。
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT,
    object_id TEXT,
    outcome TEXT NOT NULL DEFAULT 'ok',
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

-- 会话归属：旧列默认空串（owner 迁移后所有新会话都带 user_id）。
ALTER TABLE auth_sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT '';

-- 机器通道（feed/ingest bearer）→ 用户的索引：路由校验 token 时由此
-- 定位用户库；token 本体仍在各用户库的资源表（哈希存储不变）。
CREATE TABLE IF NOT EXISTS token_owner_index (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
