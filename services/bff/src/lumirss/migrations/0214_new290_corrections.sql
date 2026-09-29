-- 0214: NEW-290 简报历史更正 —— 已发布期次的追加式更正记录。
--
-- 只增不改不删（没有任何 UPDATE/DELETE 端点）：期次正文永不静默替换，
-- 订阅者看到的是「更正提示」追加在原期次之后（RSS/EML/详情同一口径）。

CREATE TABLE IF NOT EXISTS briefing_corrections (
    id TEXT PRIMARY KEY,
    briefing_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefing_corrections_issue
    ON briefing_corrections (briefing_id, created_at ASC);
