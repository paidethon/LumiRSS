-- 0131: N160 从答案生成证据笔记 —— 修订台账。
--
-- AI 答案落成的证据笔记（lumi_notes.source='ai_answer'）每次被编辑
-- 前，把上一版完整内容推入本表（provenance 保留：摘要/生成内容/
-- 人工修改三段的演进可回溯）。普通导入/手写笔记不入台账——本表只
-- 服务「从答案生成」的笔记的血统链。

CREATE TABLE IF NOT EXISTS lumi_note_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'edit',
    edited_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lumi_note_revisions_note
    ON lumi_note_revisions (note_id, edited_at DESC);
