-- 0118: N020 来源关注级别 + N014 低活跃建议接受记录。
--
-- source_overrides 追加两列（既有行 = NULL = 默认语义）：
-- - attention_level: must_read | normal | low；NULL 与 'normal' 等价
--   （默认关注级别）。消费点：通用时间线 ?attention= 服务端过滤 +
--   N041 今日队列候选排序（must_read 优先，low 垫后）。
-- - refresh_advisory: N014 低活跃建议的**已记录决定**（'accepted'）。
--   诚实边界：FreshRSS greader API 不暴露 per-feed 刷新频率——
--   接受建议不改变任何抓取行为，只把「用户已知悉该来源低活跃」
--   记在 Lumi 侧并在来源详情呈现；FreshRSS 的调度粒度由实例
--   CRON_MIN 决定，逐源频率需在 FreshRSS 原生界面调整。
ALTER TABLE source_overrides ADD COLUMN attention_level TEXT;
ALTER TABLE source_overrides ADD COLUMN refresh_advisory TEXT;
