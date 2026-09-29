-- 0190: NEW-263 译文质量反馈 —— 对具体段落标记漏译/误译/格式问题。
--
-- 每条反馈锚定 (entry_ref, block_index)：创建时刻从段缓存行快照
-- 源段文本 / 机器译文 / 人工修订（关联原文，源文后续更新不移动
-- 已建反馈），问题类型限定 omission / mistranslation / format。
--
-- status='open' 的条目构成「本人的待复核队列」（per-user 库天然
-- 隔离）；resolve / delete 显式出队。

CREATE TABLE IF NOT EXISTS translation_quality_feedback (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    issue_kind TEXT NOT NULL CHECK (issue_kind IN ('omission', 'mistranslation', 'format')),
    note TEXT NOT NULL DEFAULT '',
    source_excerpt TEXT,
    machine_excerpt TEXT,
    revised_excerpt TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_translation_quality_feedback_queue
    ON translation_quality_feedback (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_translation_quality_feedback_entry
    ON translation_quality_feedback (entry_ref, created_at DESC);
