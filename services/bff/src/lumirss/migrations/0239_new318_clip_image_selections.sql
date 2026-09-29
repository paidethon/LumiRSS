-- 0244: NEW-318 剪藏图片选择器 —— 保存网页前列出可用图片与预计体积，
-- 用户选择保存哪些，绝不默认下载全部。
--
-- 选中的图片 URL 集合随剪藏落账（1:1，urls_json 为用户显式勾选的
-- 结果；空数组 = 用户明确选择不带图）。清单（manifest）零写入零下载：
-- 图片体积来自有界探测（HEAD content-length / 有界读 ≤256KB），探测
-- 不到就诚实标 unknown，绝不猜。per-user。

CREATE TABLE IF NOT EXISTS clip_image_selections (
    clip_item_uuid TEXT PRIMARY KEY,
    urls_json TEXT NOT NULL,
    selected_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
