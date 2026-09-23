-- 0072: N015 来源分时静音 —— source_overrides 增加每周循环静音窗口。
--
-- Lumi 自有元数据（与 hidden_until/show_from 同表同性质）：mute_windows_json
-- 存 JSON 数组 [{days:[0-6], start:"HH:MM", end:"HH:MM"}]，days 为星期
-- （0=周日 … 6=周六，ISO/Python weekday 的 0=周一不同——这里与 JS
-- Date.getDay() 对齐），窗口 end<start 表示跨越午夜。
--
-- 生效面（与 hiddenUntil/showFrom 完全一致的消费点）：通用时间线显示
-- 过滤（filter_timeline_items）。抓取、搜索、阅读、已读/收藏全部不受
-- 影响——服务端照常索引。
--
-- 评估时区：服务器本地墙钟（与 mail_digest 的 '' 回退语义一致；
-- hiddenUntil/showFrom 是绝对 UTC 时刻，无墙钟概念，周循环窗口必须
-- 落在某个墙钟上——取服务器本地）。NULL = 未启用。

ALTER TABLE source_overrides ADD COLUMN mute_windows_json TEXT;
