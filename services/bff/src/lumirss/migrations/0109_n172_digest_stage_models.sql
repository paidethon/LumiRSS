-- 0111: N172 日报多模型路由——分阶段模型 + 期号运行元数据。
--
-- gpt_digest_configs 新增：
--   stage_models_json：分阶段模型（JSON 对象；键仅限 select / summarize /
--               polish；值为用户配置的模型字符串；空对象/缺省 = 全部用
--               基础模型——单次调用行为不变）。同一 provider 配置内路由，
--               服务端绝不发明模型名。
-- gpt_digest_issues 新增：
--   meta_json：期号运行元数据（JSON 对象；分阶段模型标签、润色失败
--               标记、N174 栏目注释、N175 素材篮/时长统计、N173 句子
--               映射等；'{}' = 无）。订阅输出不含 meta——只服务管理面。

ALTER TABLE gpt_digest_configs ADD COLUMN stage_models_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE gpt_digest_issues ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}';
