-- 0131 (E1): N038 按来源保留策略预演 —— source_overrides 追加保留天数。
--
-- retention_days：N038（整数天；NULL = 该来源未启用保留策略）。
-- 诚实边界（与迁移 0118 的 N014 同一取舍）：FreshRSS 没有可经 greader
-- API 使用的 per-feed 删除能力——本值**只**驱动 Lumi 派生投影
-- （search_entries）的本地裁剪预演/执行，绝不触碰 FreshRSS 原生数据；
-- 真正的物理删除需在 FreshRSS 原生界面执行（P09 委托入口直达）。
-- 投影是可再生成的派生数据：下次同步可能把上游仍存在的条目重新投影
-- 回来（此为诚实行为而非错误——本列不充当上游删除的替代品）。
ALTER TABLE source_overrides ADD COLUMN retention_days INTEGER;
