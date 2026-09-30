-- 0321: NEW-398 错误自助处理单 —— 逐步执行记录 + 脱敏求助材料来源。
--
-- runbook 步骤本体是模块内人工复核过的注册表（不落库，随代码发布）；
-- 本表只存用户的执行痕迹：每 (session, step_index) 一行结果。
-- escalate 生成的求助材料只含错误码 + 步骤结果 + 用户自填备注
-- （材料生成点负责脱敏——不含文章正文、凭据、会话标识）。

CREATE TABLE IF NOT EXISTS error_runbook_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'escalated')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    escalated_note TEXT NOT NULL DEFAULT '',
    material_json TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS error_runbook_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES error_runbook_sessions(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('tried', 'helped', 'no_effect', 'skipped')),
    note TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runbook_steps_unique
    ON error_runbook_steps(session_id, step_index);

CREATE INDEX IF NOT EXISTS idx_runbook_sessions_user
    ON error_runbook_sessions(user_id, created_at DESC);
