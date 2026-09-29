-- 0196: NEW-268 译文引用导出 —— 人工确认译文的导出台账。
--
-- 每行一次显式导出：导出时刻从段缓存行快照 原文 / 译文（人工修订
-- 优先）/ 来源（feed url + 标题，尽力取自 search_entries 投影）与
-- 机器/人工标记（human_revised = 该段存在人工修订）。用户必须显式
-- 确认（confirmed）才可导出——机器未确认的译文不给「确认译文」的
-- 引用形态。每篇上限 QUOTE_EXPORT_CAP 条（超出淘汰最旧）。

CREATE TABLE IF NOT EXISTS translation_quote_exports (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    human_revised INTEGER NOT NULL CHECK (human_revised IN (0, 1)),
    source_url TEXT NOT NULL DEFAULT '',
    feed_title TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL CHECK (format IN ('markdown', 'text')),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_translation_quote_exports_ref
    ON translation_quote_exports (entry_ref, created_at DESC);
