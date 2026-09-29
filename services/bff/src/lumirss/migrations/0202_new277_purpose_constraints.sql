-- 0202: NEW-277 模型配置用途约束 —— 每个配置档允许处理的任务类型。
--
-- allowed_purposes：JSON 数组（ai_profiles.PURPOSES 的子集，非空）。
-- 约束只对显式映射到用途的非默认档生效（default 档不可约束——
-- 未映射用途全部回落 default，约束它等于切断所有兜底）。无行 =
-- 未约束（保持现行为）。

CREATE TABLE IF NOT EXISTS ai_purpose_constraints (
    profile_id TEXT PRIMARY KEY,
    allowed_purposes TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
