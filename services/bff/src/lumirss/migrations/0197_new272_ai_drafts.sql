-- 0197: NEW-272 AI 草稿版本对照 —— 同一材料在不同提示方案下生成的草稿。
--
-- 分组键 (entry_ref, material_hash)：同一材料的多份草稿并列对照；
-- kept 单选（同组互斥，切换保留 = 显式用户选择）。草稿只是候选文本：
-- 保留/删除草稿绝不写 ai_summaries、lumi_notes 等人工结论面。
-- material_hash 可空串（客户端拿不到内容哈希时诚实留空，分组退化为
-- entry_ref 单组）。

CREATE TABLE IF NOT EXISTS ai_drafts (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    material_hash TEXT NOT NULL DEFAULT '',
    scheme_label TEXT NOT NULL,
    prompt_text TEXT NOT NULL DEFAULT '',
    draft_text TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'summary',
    kept INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_drafts_group
    ON ai_drafts (entry_ref, material_hash, created_at ASC);
