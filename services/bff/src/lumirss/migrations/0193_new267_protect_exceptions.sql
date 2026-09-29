-- 0193: NEW-267 专有名词保护清单 —— 按条目的「当前任务例外」。
--
-- N083 的 protect=1 术语默认逐条保留（prompt 指令 + 后处理还原）。
-- 本表登记例外：(entry_ref, term) —— 该术语在这篇条目的后续生成中
-- 不再列入保护（其余条目不受影响）。已有缓存译文原样展示（不悄悄
-- 改变）；例外只作用于其后的新生成。

CREATE TABLE IF NOT EXISTS translation_protect_exceptions (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    term TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (entry_ref, term)
);

CREATE INDEX IF NOT EXISTS idx_translation_protect_exceptions_ref
    ON translation_protect_exceptions (entry_ref);
