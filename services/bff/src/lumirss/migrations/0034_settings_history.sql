-- 0034: F33 设置变更历史 —— 每次可回退设置变更的差异记录。
--
-- 只记录 portable 设置（设计上不含任何密钥）。diff_json =
-- {"<key>": {"before": x, "after": y}}，只含实际变化的键。
-- 保留最近 20 条（插入时裁剪），action ∈ update/revert/reset。

CREATE TABLE IF NOT EXISTS settings_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TEXT NOT NULL,
    action TEXT NOT NULL,
    diff_json TEXT NOT NULL
);
