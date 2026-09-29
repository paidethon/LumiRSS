-- 0271: NEW-348 数据驻留说明 —— 管理员补充的驻留注释（实例级，
-- 存控制库；成员只读）。固定键 + 自定义键（^[a-z0-9_]{1,40}$）。
-- 未注释的固定键在响应中如实标 unknown（提示管理员补充）。

CREATE TABLE IF NOT EXISTS residency_notes (
    key TEXT PRIMARY KEY,
    note TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
