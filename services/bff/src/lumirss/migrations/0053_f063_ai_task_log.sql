-- 0053: F063 AI 任务中心 — AI 生成任务的尽力而为埋点日志。
--
-- kind：summary / translation / conversation / quiz / cards / compare /
--       ask_batch（后三类为 W4 新端点预留，写入即记录）；
-- status：done / failed（failed 带 error_type，诚实区分上游失败类型）；
-- entry_ref：entry 类任务可定位文章（NULL = 非单篇任务）；
-- duration_ms / input_chars / model：诊断信息（未知留空，不编造）。
-- 记录时裁剪到最近 500 条（有界存储）；读取接口默认/上限 50。

CREATE TABLE ai_task_log (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN (
        'summary', 'translation', 'conversation', 'quiz', 'cards',
        'compare', 'ask_batch'
    )),
    entry_ref TEXT,
    status TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    model TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    input_chars INTEGER,
    error_type TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX ai_task_log_created ON ai_task_log (created_at DESC);
