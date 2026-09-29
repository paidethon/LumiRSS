-- 0258: NEW-334 空间成员到期管理 —— 邀请成员时可指定权限到期时间；
-- 到期只撤销空间权限，不删除其个人账户（复用邀请 expires_at 的到期
-- 语义：到期后访问即失效）。本表是到期/续期的审计台账；权限判定
-- 以 space_members.expires_at 为唯一事实源（读取时即时判定）。

CREATE TABLE IF NOT EXISTS space_member_expiry_log (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_space_member_expiry_log_space
    ON space_member_expiry_log (space_id, created_at DESC);
