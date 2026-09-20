-- 0038: F019 Library 回收站 —— library_items 增加软删标记。
--
-- library_items 是书签与剪辑共用的身份根：deleted_at 放在身份根上，
-- 一个标记同时覆盖两个域；标签/工作区关联挂在 item uuid 上，软删与
-- 恢复都不触碰关联（恢复后原样出现）。deleted_at 非空 = 在回收站；
-- 永久删除沿用既有 DELETE（FK 级联书签/剪辑行 + 搜索投影清理）。
-- FreshRSS RSS 域数据（entries/已读/收藏）完全不受本迁移影响。

ALTER TABLE library_items ADD COLUMN deleted_at TEXT;
