-- 0286: NEW-367 搜索会话回溯 —— 一次研究过程的查询序列与选中结果。
--
-- steps_json：[{query, filters, at, refs:[选中结果]}]（≤50 步，每步
-- 选中 ≤100 ref）；current_step 指向最后一步 —— 重新打开即接续到
-- 最后一步（不回退、不重放）。per-user 库表：A 的会话对 B 不可见。

CREATE TABLE IF NOT EXISTS search_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    steps_json TEXT NOT NULL DEFAULT '[]',
    current_step INTEGER NOT NULL DEFAULT -1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_sessions_updated
    ON search_sessions (updated_at DESC);
