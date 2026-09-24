-- 0089: 实例级设置（P0 公开注册策略 allow_public_registration）。
--
-- 实例级（非每用户）开关的唯一真源，存控制库。默认值由应用层
-- 定义（allow_public_registration 缺省 = false：存量实例升级与全新
-- 部署都保持注册关闭，必须由运营者在 /admin 显式打开）。
-- 与 0067 同理：本表在每用户库也会创建但恒空——单序列迁移的现实，
-- 只有控制库写入行。
--
-- 审计：改动经 AccountsStore.audit 落 audit_log（actor=管理员），
-- 本表不重复记历史，只存当前值。

CREATE TABLE IF NOT EXISTS instance_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    updated_by TEXT
);
