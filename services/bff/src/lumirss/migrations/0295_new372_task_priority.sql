-- 0295: NEW-372 任务优先级调整 —— 后台逐账户清扫顺序的显式优先级。
--
-- 每账户至多一行；无行 = 默认优先级（同层保持既有顺序）。
-- 调整只影响下一轮清扫的顺序快照：已在执行中的同步绝不被打断
-- （无抢占代码路径，执行点在 main.py 的搜索投影循环——清扫开始时
-- 取一次顺序快照，本轮内不再读取）。
-- 行属于 control 库；普通用户只能读写自己的行（member 路由固定
-- 以会话身份为主语，不存在跨账户写入口）。

CREATE TABLE IF NOT EXISTS admin_task_priorities (
    user_id TEXT PRIMARY KEY,
    priority INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 3),
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
