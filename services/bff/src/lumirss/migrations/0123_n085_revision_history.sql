-- 0123: N085 译文修订历史。
--
-- F062 的修订每段只保留当前一份（user_revision 覆盖即丢）。N085 在
-- 覆盖发生前把上一版修订推入历史栈（每段上限 5 条，超出淘汰最旧），
-- 支持「恢复上一版」逐版回退。
--
-- 历史以 (entry_ref, block_index) 为语义单位——与 F062 修订一致
-- （修订锚定源段而非某个缓存变体行）；old_text 是被替换的那一版
-- 修订文本，replaced_at 是被替换的时刻。

CREATE TABLE IF NOT EXISTS ai_translation_revision_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_ref TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    old_text TEXT NOT NULL,
    replaced_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_revision_history_segment
    ON ai_translation_revision_history (entry_ref, block_index, replaced_at DESC);
