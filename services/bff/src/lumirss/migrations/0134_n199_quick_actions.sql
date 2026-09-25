-- 0134: N199 自定义多步快捷操作 —— 具名 2-3 步序列（SAFE 动作白名单）。
--
-- steps_json 形如 [{"action":"add_to_queue","params":{...}}, ...]；
-- 本表只存「定义」。执行永远在 Web 端逐步走各动作的 NORMAL 端点
-- （无服务端旁路）：每一步都过它原本的鉴权/确认路径，出错即停。
-- per-user 库 = 只可能是本人的操作。

CREATE TABLE IF NOT EXISTS quick_actions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
