-- 0200: NEW-275 批量 AI 任务审批单 —— 执行前清单与预算。
--
-- 审批单 = 准备处理的文章 + 任务类型 + 预算（最多消耗的 AI 调用数）。
-- status: draft → approved → completed/cancelled；items.status:
-- pending → done|failed|quota_exceeded|ai_disabled|over_budget|cancelled。
-- 尚未开始的项可取消；已开始的项不动。

CREATE TABLE IF NOT EXISTS ai_batch_approvals (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    budget_calls INTEGER NOT NULL,
    used_calls INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    approved_at TEXT,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS ai_batch_approval_items (
    id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error_type TEXT,
    finished_at TEXT,
    ord INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ai_batch_items
    ON ai_batch_approval_items (approval_id, ord ASC);
