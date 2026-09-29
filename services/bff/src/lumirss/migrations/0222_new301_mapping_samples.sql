-- 0227: NEW-301 API 字段映射编辑器 —— 用户粘贴 JSON 样本，映射
-- 标题/正文/日期，预览后绑定到既有 API 来源（复用 api_sources 的
-- field_map 存储与 update 失效语义）。
--
-- 样本按来源归属（per-user 库，来源本身就在该用户的 api_sources）；
-- 每来源样本数与样本体积在应用层受限（≤10 条 / ≤256KB）。

CREATE TABLE IF NOT EXISTS api_mapping_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uuid TEXT NOT NULL,
    label TEXT NOT NULL,
    sample_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mapping_samples_source
    ON api_mapping_samples(source_uuid, id);
