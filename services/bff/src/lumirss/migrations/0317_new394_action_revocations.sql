-- 0317: NEW-394 通知动作撤销登记 —— 「原事件已撤销/权限失效」的事实表。
--
-- 每条通知至多一条撤销登记（UNIQUE notification_id；再次撤销 = 更新
-- 原因与时间，最新事实覆盖）。读取侧（0314 列表 / 0315 聚合）联查
-- 本表：命中即 invalidReason 生效、actionable 强制为假——前端不再
-- 渲染任何按钮。撤销登记是显式动作（上游撤销流程调用），绝不因
-- 时间流逝或行为推断自动产生。

CREATE TABLE IF NOT EXISTS notification_action_revocations (
    notification_id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    revoked_at TEXT NOT NULL
);
