-- 0297: NEW-374 用户资源账单 —— 账单本体全部实时派生（每账户各数据
-- 类别行数 / 磁盘字节 / AI 调用计数），不落快照表；本迁移只落一件
-- 必须持久化的事：管理员查看「他人」账单的查阅台账。
--
-- 账单口径 = member 自查与 admin 查阅共用同一模块函数，只有主语
-- 不同；内容永远是计数/字节，绝无文章内容或私人正文。

CREATE TABLE IF NOT EXISTS admin_resource_bill_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    viewer_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    viewed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_resource_bill_views_target
    ON admin_resource_bill_views(target_user_id, viewed_at DESC);
