-- 0036: F001 来源新鲜度预警 —— source_overrides 增加 per-source 阈值。
--
-- Lumi 自有元数据（非 FreshRSS RSS 域数据）：stale_alert_hours 为该来源
-- 的「超期小时数」阈值；NULL = 该来源未启用新鲜度预警。
-- 判定口径由 /api/v1/sources/stale 的 basis 字段承载（latest_entry |
-- fetch_time | unknown）——发布时间旧 ≠ 抓取失败，绝不把发布时间
-- 标成抓取成功。

ALTER TABLE source_overrides ADD COLUMN stale_alert_hours INTEGER;
