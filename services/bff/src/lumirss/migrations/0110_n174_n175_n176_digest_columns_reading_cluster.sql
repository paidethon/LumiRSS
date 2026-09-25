-- 0112: N174 栏目结构 + N175 阅读时长控制 + N176 引用去重（同事件聚合）。
--
-- gpt_digest_configs 新增三列：
--   columns_json：固定栏目结构（JSON 数组，≤8 项；'[]' = 不启用）。
--               每项 {"name": 栏目名, "count": 条目上限(1–20),
--               "emptyPolicy": "hide"|"placeholder"}——生成提示按此结构
--               约束，输出校验强制 sections == 配置栏目（空栏目按策略
--               隐藏或放置「本栏目今日无内容」占位，绝不编造内容）。
--   target_reading_minutes：目标阅读时长（分钟；0 = 不启用）。超过预算
--               的条目按优先级移入期号 meta 的素材篮（leftoverPool），
--               绝不静默删除；估算口径 chars/400 每分钟。
--   cluster_enabled：同事件聚合开关（0 = 关，默认）。开启后选材阶段把
--               标题相似（jaccard ≥ 0.6）且 48 小时内发布的条目聚成一条
--               多来源条目；仅标题相似但跨日（>48h）绝不合并。

ALTER TABLE gpt_digest_configs ADD COLUMN columns_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE gpt_digest_configs ADD COLUMN target_reading_minutes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE gpt_digest_configs ADD COLUMN cluster_enabled INTEGER NOT NULL DEFAULT 0;
