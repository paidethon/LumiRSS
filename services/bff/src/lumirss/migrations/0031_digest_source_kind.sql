-- 0031: F04 收藏/稍后读转简报 —— 日报材料源可切换。
--
-- source_kind：
--   'window'    默认。窗口内订阅内容（历史语义）；
--   'read_later' 稍后读队列中的 RSS 条目（用户显式保存的内容）；
--   'starred'    FreshRSS 收藏条目。
-- 保存类来源不适用时间窗口（语义不同），也不应用来源白名单
-- （白名单约束的是订阅抓取面）。生成不改变已读/队列状态。

ALTER TABLE gpt_digest_configs ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'window';
