-- 0199: NEW-274 AI 结果引用核验 —— 逐条引用定位台账。
--
-- answer_text：被核验的回答原文；citations：逐条引用 JSON
-- （index / entryRef / claim / status found|not_found|entry_unavailable /
-- excerpt / offset）；checked：仅在用户显式确认后置 1（有未定位引用时
-- 必须带 confirmMissing=true ——「用户确认后才能标为已核对」）。

CREATE TABLE IF NOT EXISTS ai_citation_checks (
    id TEXT PRIMARY KEY,
    answer_text TEXT NOT NULL,
    citations TEXT NOT NULL DEFAULT '[]',
    checked INTEGER NOT NULL DEFAULT 0,
    confirmed_missing INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    checked_at TEXT
);
