-- 0055: F066 per-source AI 禁用（source_overrides 扩展）。
--
-- ai_disabled = 1：该来源条目不参与任何 AI 消耗（摘要/译文/对话/问答
-- → 403；gpt_digest 选材排除；agent 工具结果过滤；RAG 索引移除）。
-- 派生数据（已生成的摘要/译文）保留不删，仅不再更新；
-- 重新启用后下次重建/增量恢复纳入（RAG 按移除前状态核实）。
-- 本迁移同时收口 W4：合并 F069/F070 所需的两张表（结构不变，
-- 只是同文件落两表，节省迁移号）。
ALTER TABLE source_overrides ADD COLUMN ai_disabled INTEGER NOT NULL DEFAULT 0;

-- F069 文章阅读自测：payload_json 存题目（无答案）；answers_json 存
-- 答案+evidence（评分时使用，生成响应绝不返回）。
CREATE TABLE quiz_sessions (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX quiz_sessions_entry ON quiz_sessions (entry_ref);

-- F070 知识卡片：同 (entry_ref, concept) 幂等 upsert。
CREATE TABLE knowledge_cards (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    concept TEXT NOT NULL,
    explanation TEXT NOT NULL,
    source_quote TEXT NOT NULL DEFAULT '',
    quote_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (entry_ref, concept)
);
