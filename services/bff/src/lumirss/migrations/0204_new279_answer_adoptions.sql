-- 0204: NEW-279 问答结论采纳 —— 回答中的结论连同引用移入个人笔记。
--
-- 每条采纳 = 一个结论 + 引用清单（JSON：index/entryRef）+ 落到的
-- lumi_notes 笔记（note_uuid；笔记正文带「来源：AI」标记行）。
-- 改写走 PATCH：笔记若被人工改过（整篇内容 sha256 与写入时漂移——
-- updatedAt 秒级精度不足以区分同一秒内的编辑）→ 409 note_diverged，
-- 绝不静默覆盖人工修改。删除采纳不删笔记。

CREATE TABLE IF NOT EXISTS ai_answer_adoptions (
    id TEXT PRIMARY KEY,
    entry_ref TEXT,
    conclusion TEXT NOT NULL,
    citations TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL DEFAULT '',
    note_uuid TEXT NOT NULL,
    note_updated_at TEXT NOT NULL,
    note_content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_answer_adoptions_created
    ON ai_answer_adoptions (created_at DESC);
