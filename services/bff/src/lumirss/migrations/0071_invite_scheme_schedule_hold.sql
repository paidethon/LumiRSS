-- 0071: 邀请方案（N001）/ 预约生效邀请（N002）/ 邀请容量预约（N003）。
--
-- invite_schemes：运营者保存的命名邀请方案（TTL、初始订阅源、是否在
-- 邀请创建时预约一个 FreshRSS 池名额、配额备注）。一个方案可批量生成
-- N 个互相独立的一次性邀请，每个邀请记录 scheme_id；激活时把方案写入
-- 账号行（管理台成员列表显示方案名）并尽力订阅初始源（失败逐条如实
-- 返回，绝不阻塞激活）。
--
-- invites 扩列（全部可空——旧邀请行为完全不变）：
--   scheme_id          生成该邀请的方案；
--   not_before         预约生效时间（epoch 秒）——服务器时钟是唯一时钟，
--                      生效前兑换得到稳定 403 invite_not_active；
--   held_pool_account  创建时预约的 FreshRSS 池账号用户名
--                      （ready → held → assigned 状态机；撤销/过期自动
--                      释放回 ready，激活时原子转换为 assigned）。
--
-- users.scheme_id：账号由哪个方案激活而来（仅目录元数据，不含内容）。

CREATE TABLE IF NOT EXISTS invite_schemes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ttl_hours INTEGER NOT NULL,
    initial_source_urls TEXT NOT NULL DEFAULT '[]',
    freshrss_pool_hold INTEGER NOT NULL DEFAULT 0,
    quota_note TEXT,
    created_by TEXT,
    created_at INTEGER NOT NULL
);

ALTER TABLE invites ADD COLUMN scheme_id TEXT;
ALTER TABLE invites ADD COLUMN not_before INTEGER;
ALTER TABLE invites ADD COLUMN held_pool_account TEXT;
ALTER TABLE users ADD COLUMN scheme_id TEXT;

CREATE INDEX IF NOT EXISTS idx_invites_scheme ON invites(scheme_id);

-- 池状态机扩展：ready → held → assigned（释放回到 ready）。SQLite 无法
-- 修改既有 CHECK 约束，按标准建新表-拷贝-换名前向迁移；已分配行原样
-- 保留（已激活账号永不删除）。
CREATE TABLE freshrss_pool_extended (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    freshrss_username TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'ready' CHECK (state IN ('ready', 'assigned', 'held')),
    held_invite TEXT,
    assigned_user TEXT,
    assigned_at INTEGER,
    created_at INTEGER NOT NULL
);

INSERT INTO freshrss_pool_extended (id, freshrss_username, base_url, state, held_invite, assigned_user, assigned_at, created_at)
SELECT id, freshrss_username, base_url, state, NULL, assigned_user, assigned_at, created_at FROM freshrss_pool;

DROP TABLE freshrss_pool;

ALTER TABLE freshrss_pool_extended RENAME TO freshrss_pool;
