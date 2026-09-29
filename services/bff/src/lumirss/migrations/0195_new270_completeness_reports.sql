-- 0195: NEW-270 翻译完整性报告 —— 任务结束的逐段完整性台账。
--
-- 每行一次完整性报告快照：total/translated/failed/missing/skipped
-- 计数 + filled（本次用户显式补译的段数）。用户选择补译时写一行
-- （补译动作只发缺失/失败段，已有结果不动）；列表供回看「哪里
-- 缺、补了多少」，而不是只看成功百分比。每篇上限 REPORT_CAP 条。

CREATE TABLE IF NOT EXISTS translation_completeness_reports (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    total INTEGER NOT NULL,
    translated INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    missing INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    filled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_translation_completeness_reports_ref
    ON translation_completeness_reports (entry_ref, created_at DESC);
