-- 0051: F061 保存视图私有 Atom 订阅。
--
-- feed_secret：secrets 风格随机 hex（token_hex(16)），生成于首次启用
-- 或轮换；NULL = 未启用。公开路由 /feeds/views/{view_id}.{secret}.atom
-- 校验该值；管理端 API 只暴露 hasFeedToken 布尔，绝不返回 secret。
-- 轮换 = 覆写，旧地址立即失效。

ALTER TABLE saved_searches ADD COLUMN feed_secret TEXT;
