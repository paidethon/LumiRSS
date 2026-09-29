-- 0272: NEW-349 隐私检查向导 —— 逐项「撤回」动作留痕。向导绝不
-- 提供一键全删：每次撤回一行，动作与对象如实记录。

CREATE TABLE IF NOT EXISTS privacy_review_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    ref TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);
