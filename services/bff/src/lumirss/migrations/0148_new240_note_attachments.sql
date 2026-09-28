-- 0148: NEW-240 笔记附件清单 —— 笔记上的本人小附件（BLOB 内联）。
--
-- 「小附件」限额：单文件 ≤256KB、每笔记总量 ≤1MB、每笔记 ≤10 个
-- （应用层执行；这里只存字节）。移除附件只删本表行——笔记正文
-- （lumi_notes.content_md）永不被附件操作触碰。

CREATE TABLE IF NOT EXISTS note_attachments (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL,
    content BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_note_attachments
    ON note_attachments (note_id, created_at ASC);
