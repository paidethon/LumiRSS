-- 0314: NEW-391 应用内通知收件箱 —— 真实事件集中落点。
--
-- user_notifications（control 库）：每行一条**已发生**的真实事件
-- （任务完成/失败、共享变化、帮助回复等），写入方是各自域的收尾
-- 逻辑（本组内：NEW-399 管理员修订回复；record_event 是跨域登记
-- 函数）。通知不是猜测出来的——没有事件就没有行。
--
-- per-user 隔离靠 user_id 列 + 全部读路径 WHERE user_id = 会话身份；
-- ref 只存不透明引用串（entryRef 等），绝不内嵌正文或凭据。
--
-- actionable 只表示「记录事件时动作存在」；读取时与 NEW-394 的撤销
-- 登记联判——已撤销的事件读取侧强制失效（不提供不可执行按钮）。

CREATE TABLE IF NOT EXISTS user_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('task_completed', 'task_failed', 'share_event', 'help_answered')),
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    ref TEXT NOT NULL DEFAULT '',
    actionable INTEGER NOT NULL DEFAULT 0,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_notifications_user_time
    ON user_notifications(user_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_notifications_user_unread
    ON user_notifications(user_id, read_at) WHERE read_at IS NULL;
