-- 0046: F035 固定保存视图 + 完整意图持久化。
--
-- pinned/pin_order：首页侧栏「固定视图」块的显示顺序；filters_json
-- 存构建器完整意图（feedRef/unreadOnly/favoriteOnly/hasSummary/from/
-- to/intitle/phrase/exclude）。老视图 filters_json 为 NULL → 走既有
-- q 解析（向后兼容）。

ALTER TABLE saved_searches ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE saved_searches ADD COLUMN pin_order INTEGER;
ALTER TABLE saved_searches ADD COLUMN filters_json TEXT;
