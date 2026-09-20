-- 0061: F093 RAG 重建作业（暂停/断点续建）+ F100 内容 hash 列。
--
-- rag_jobs：一次 rebuild 一行；cursor_json 记录文档页游标（含各 ref
-- 的分块序号状态），进程重启后仍可从游标续建；stats_json 记录已产出
-- 分块数/跳过来源等。status: running | paused | done | failed。
CREATE TABLE rag_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'rebuild',
    status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'done', 'failed')),
    cursor_json TEXT,
    stats_json TEXT,
    updated_at TEXT NOT NULL
);

-- F100 版本一致性：分块存储其正文 hash（SHA-256），与当前投影正文
-- hash 比对即可列出失配条目。旧行（本迁移前写入）为 NULL——视为
-- 未知，等价于失配（诚实列出，修复后补齐）。
ALTER TABLE rag_chunks ADD COLUMN content_hash TEXT;
