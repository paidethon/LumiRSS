-- 0060: F091 RAG 索引排除规则 —— source_overrides.rag_excluded。
--
-- rag_excluded = 1：该来源条目不进入 RAG 语料（重建排除 + 现有分块
-- 移除）。与 ai_disabled 的优先级：ai_disabled=1 严格优先——即使
-- rag_excluded=0，AI 禁用源仍然排除（F066 语义不被本列削弱）。
-- 本列只影响派生索引，原始条目数据不受任何影响。
ALTER TABLE source_overrides ADD COLUMN rag_excluded INTEGER NOT NULL DEFAULT 0;
