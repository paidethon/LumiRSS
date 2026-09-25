-- 0110: N171 日报编辑计划——按星期发布 + 周末独立时点。
--
-- gpt_digest_configs 新增两列：
--   days_json：发布日集合（JSON 数组，0=周一 … 6=周日；'[]' = 每天，
--               与历史行为一致）。plan_run 在非发布日返回 None——已发布
--               期号的幂等语义不变（issue_key 唯一约束照旧）。
--   weekend_hours：周六/周日的独立发布时点（逗号分隔小时，最多 4 个；
--               '' = 沿用周一至周五的 hour/slots 计划）。

ALTER TABLE gpt_digest_configs ADD COLUMN days_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE gpt_digest_configs ADD COLUMN weekend_hours TEXT NOT NULL DEFAULT '';
