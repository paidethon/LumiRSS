-- 0323: NEW-400 个人功能使用清理 —— 显式关闭动作的留痕。
--
-- 「启用中」的事实永远来自各功能自己的表（规则数/静默设置/回退
-- 偏好/处理单），本表只记录用户**本人**的关闭动作与数据保留选择
-- （keep = 关开关留数据；delete = 一并清除）。没有任何定时器或行为
-- 推断会写这张表——自动关闭在本面不存在，这是契约不是疏忽。

CREATE TABLE IF NOT EXISTS advanced_module_closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    module_id TEXT NOT NULL,
    retention TEXT NOT NULL CHECK (retention IN ('keep', 'delete')),
    detail TEXT NOT NULL DEFAULT '',
    closed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_module_closures_user_time
    ON advanced_module_closures(user_id, closed_at DESC);
