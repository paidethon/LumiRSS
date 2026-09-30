-- 0300: NEW-377 后台任务阻塞定位 —— 每次诊断把当时的阻塞观测落账
-- （类别 + 范围 + 脱敏计数详情），供历史回看与交接摘要（NEW-380）
-- 引用；实时诊断每次重算，不读旧账下结论。详情只含计数/键名/
-- 账户 id，绝无来源 URL、文章内容或秘密值。

CREATE TABLE IF NOT EXISTS admin_task_blockers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL CHECK (category IN ('quota', 'rate_limit', 'lock', 'dependency')),
    scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    diagnosed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_task_blockers_time
    ON admin_task_blockers(diagnosed_at DESC);
