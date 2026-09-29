-- 0198: NEW-273 提示模板试运行 —— 启用前在少量样本上的试跑台账。
--
-- template_text：被试跑的模板原文（候选，不必已保存为 qa_template）；
-- results：逐样本 JSON（title / inputChars / output / status /
-- errorType，诚实记录，不估算 token）；promoted_template_id 非空 =
-- 已决定启用（升级为正式 qa_template）。

CREATE TABLE IF NOT EXISTS ai_template_trials (
    id TEXT PRIMARY KEY,
    template_text TEXT NOT NULL,
    sample_kind TEXT NOT NULL,
    results TEXT NOT NULL DEFAULT '[]',
    promoted_template_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_template_trials_created
    ON ai_template_trials (created_at DESC);
