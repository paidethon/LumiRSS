-- 0127: N159 检索质量收藏 —— 私有 RAG 评测样例（本用户库本地数据）。
--
-- 保存时服务端立即执行一次真实检索并捕获命中（actual_refs_json），
-- 之后 rerun 重放同一查询与存储的实际值做差分。expected/scope 以
-- JSON 列存储（引用与过滤条件，绝无正文内容复制）。
--
-- 本地表是「本地评测工作台」数据：绝不进入任何导出/分享包，也不属于
-- 备份范围组件（backup_scope 的组件→表映射刻意不含本表）——评测样例
-- 只对本用户当前库有意义，跨恢复还原没有语义。上限 50 条由存储层
-- 强制（409 eval_sample_limit），表上不加硬约束（诚实报错优于静默
-- 挤出最旧行）。
CREATE TABLE rag_eval_samples (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    expected_refs_json TEXT NOT NULL,
    actual_refs_json TEXT NOT NULL,
    scope_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_rag_eval_samples_created ON rag_eval_samples(created_at DESC, id DESC);
