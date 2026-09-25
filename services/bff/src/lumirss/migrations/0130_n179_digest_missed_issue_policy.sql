-- N179 缺刊处理策略（每用户业务库，gpt_digest_configs）：
-- missed_issue_policy：backfill（默认，补刊——现有行为）|
-- merge_into_next（错过的窗口材料并入下一期，经素材池）| skip（跳过并记录）。
-- skip_log_json：[{date, reason}]，cap 30（store 层裁剪），供配置 UI 展示。
ALTER TABLE gpt_digest_configs ADD COLUMN missed_issue_policy TEXT NOT NULL DEFAULT 'backfill';
ALTER TABLE gpt_digest_configs ADD COLUMN skip_log_json TEXT NOT NULL DEFAULT '[]';
