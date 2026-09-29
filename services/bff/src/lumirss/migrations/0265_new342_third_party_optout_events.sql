-- 0265: NEW-342 第三方请求清单 —— 可选外发请求的开关动作留痕
-- （关闭/恢复）。清单本体从当前配置实时推导（无影子副本）；本表只
-- 记录「谁在何时执行了哪个开关动作」，供隐私检查向导（NEW-349）
-- 与本人回顾。

CREATE TABLE IF NOT EXISTS third_party_optout_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);
