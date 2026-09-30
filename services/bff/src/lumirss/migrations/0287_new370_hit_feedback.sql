-- 0287: NEW-370 搜索结果评注 —— 用户对某命中的「有用/无关」标记与
-- 原因，以及仅本人显式启用后才生效的排序方案开关。
--
-- search_hit_feedback：每个 (query_key, entry_ref) 一条（再次标记即
-- 覆盖 verdict/reason，保留首次 created_at）。
-- search_ranking_settings：单行开关（id=1），默认关闭——反馈绝不
-- 自动改变默认搜索排序；只有用户显式 enable 后，reranked 端点才
-- 返回「有用优先」的顺序。
--
-- per-user 库表：A 的反馈与开关对 B 不可见。

CREATE TABLE IF NOT EXISTS search_hit_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_key TEXT NOT NULL,
    query TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    entry_title TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL CHECK (verdict IN ('useful', 'irrelevant')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (query_key, entry_ref)
);

CREATE INDEX IF NOT EXISTS idx_search_hit_feedback_query
    ON search_hit_feedback (query_key, updated_at DESC);

CREATE TABLE IF NOT EXISTS search_ranking_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    scheme TEXT NOT NULL DEFAULT 'hit_feedback',
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
