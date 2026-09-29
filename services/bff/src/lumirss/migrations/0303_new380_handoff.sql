-- 0303: NEW-380 运维交接摘要 —— 按真实记录生成的脱敏交接清单。
-- payload 在生成时即为脱敏形态（秘密只有 已配置/未配置 状态位）；
-- confirm 后才允许导出，导出打一次 exported_at 戳。

CREATE TABLE IF NOT EXISTS admin_handoff_summaries (
    id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
    exported_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_by TEXT,
    confirmed_at TEXT
);
