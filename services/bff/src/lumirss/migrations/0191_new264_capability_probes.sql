-- 0191: NEW-264 翻译服务能力比较 —— 用户选择的少量非敏感样本的
-- 对照运行记录（本地留档，便于复看；绝不自动重发）。
--
-- 每行是一次显式探测：samples_json = 用户输入的样本（原文），
-- sides_json = 每个已配置提供方逐样本的结果/耗时/错误（ephemeral
-- 运行不写翻译缓存；本表只存用户可见的报告本体）。每人保留最近
-- PROBE_HISTORY_CAP 条（超出淘汰最旧）。

CREATE TABLE IF NOT EXISTS translation_capability_probes (
    id TEXT PRIMARY KEY,
    samples_json TEXT NOT NULL,
    sides_json TEXT NOT NULL,
    available INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_translation_capability_probes_time
    ON translation_capability_probes (created_at DESC);
