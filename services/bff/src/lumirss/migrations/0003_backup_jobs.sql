-- 0018: Backup / restore job ledger.
--
-- Ownership boundary: FreshRSS remains the RSS-domain source of truth.
-- This table holds ONLY Lumi-owned backup/restore job metadata (status,
-- stage, target, safe summary). Backup payloads live on disk / WebDAV,
-- never in SQLite. Secrets are never stored here.

CREATE TABLE backup_jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (
        type IN ('full', 'safety', 'restore')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')
    ),
    stage TEXT,
    target TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    summary TEXT,
    safe_error TEXT
);

CREATE INDEX backup_jobs_created_at ON backup_jobs (created_at);
