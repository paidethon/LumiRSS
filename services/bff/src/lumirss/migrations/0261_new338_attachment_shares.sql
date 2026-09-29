-- 0261: NEW-338 共享附件访问清单 —— 所有者把**自己的**附件以元数据
-- 快照显式共享进空间（ref/名称/类型/大小）；管理者可查看全清单并逐项
-- 撤销授权，所有者也可撤销自己的共享。撤销只关闭空间授权行（保留
-- 台账历史），绝不触碰所有者 per-user 库里的私人文件本身。
--
-- 诚实边界：本表面只承载元数据台账；附件字节存在所有者自己的
-- per-user 库/资产根里，不跨用户复制（下载通道不在本切片范围）。

CREATE TABLE IF NOT EXISTS space_attachment_shares (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    owner_username TEXT NOT NULL,
    attachment_ref TEXT NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    revoked_by TEXT,
    revoked_by_username TEXT
);

CREATE INDEX IF NOT EXISTS idx_space_attachment_shares_space
    ON space_attachment_shares (space_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_space_attachment_shares_owner
    ON space_attachment_shares (owner_user_id, space_id);
