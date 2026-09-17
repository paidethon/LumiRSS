-- 0029: F19 稍后读延后 —— 保存项可延后到指定日期，到期自动回到
-- read-later 时间线（过滤在读取侧：snoozed_until > now 的行不出现在
-- 时间线；行本身保留，原状态不受影响，无推送通知依赖）。

ALTER TABLE workspace_items ADD COLUMN snoozed_until TEXT;
