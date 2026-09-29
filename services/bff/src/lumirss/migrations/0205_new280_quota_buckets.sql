-- 0205: NEW-280 AI 配额分桶 —— 用户把可用额度分到翻译/摘要/问答等用途。
--
-- purpose：ai_profiles.PURPOSES 之一；max_calls：该用途每窗口调用上限
-- （应用层执行，计数复用 ai_usage 表，键 "bucket:{purpose}:{window}"，
-- 与全局配额同一原子预占原语）。purpose 无行 = 未分桶 → 沿用全局配额。
-- 超额 → 429 带分桶现状（调整入口），绝不静默超额。

CREATE TABLE IF NOT EXISTS ai_quota_buckets (
    purpose TEXT PRIMARY KEY,
    max_calls INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
