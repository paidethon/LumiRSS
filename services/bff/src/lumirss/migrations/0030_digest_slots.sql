-- 0030: F02 早晚刊/多餐次 —— 同一主题日报一天多个发布时点。
--
-- slots：逗号分隔的发布小时列表（如 "8,20"；空 = 退回单 hour 字段，
-- 老配置零迁移成本）。窗口按相邻时点切分：[上一时点, 本时点)，跨天
-- 回溯，天然不重叠不漏项；期号 = 日期-时点（YYYY-MM-DD-HH），
-- (config_id, issue_key) 唯一约束承担补刊/重启/错过时刻的去重。
-- 单时点老配置（slots 为空）期号保持 YYYY-MM-DD 不变（兼容既有期刊）。

ALTER TABLE gpt_digest_configs ADD COLUMN slots TEXT NOT NULL DEFAULT '';
