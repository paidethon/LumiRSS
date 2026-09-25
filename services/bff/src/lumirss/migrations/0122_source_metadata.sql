-- 0120: 来源元数据扩展（F032 语言 / F034 未读警戒阈值 / F031 同步优先级）。
--
-- 仍是 Lumi 自有覆盖维度（不触碰 FreshRSS RSS 域真源）：
--   language：来源主要语言标注（ISO 639-1 小写，NULL=未标注；
--     仅元数据与筛选消费，不做自动检测）。
--   unread_alert_threshold：未读数警戒阈值（投影口径的未读计数超过
--     该值时来源列表警示；NULL=未设置）。
--   sync_priority：搜索投影同步优先级（0=普通 1=高 2=低；
--     NULL=普通；只影响 Lumi 投影同步顺序，不改 FreshRSS 调度）。

ALTER TABLE source_overrides ADD COLUMN language TEXT;
ALTER TABLE source_overrides ADD COLUMN unread_alert_threshold INTEGER;
ALTER TABLE source_overrides ADD COLUMN sync_priority INTEGER;
