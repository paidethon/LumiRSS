-- 0174: NEW-248 来源链接去追踪预览 —— 用户保留参数表。
--
-- detrack_kept_params：用户标记为「必须保留」的查询参数（登录态、
-- 内容选择等），去追踪预览永远跳过。追踪参数识别是内置已知清单
-- （utm_* / fbclid / gclid 等公开追踪参数）；未知参数保守保留、
-- 绝不删除。预览是纯计算（零写入），本表是唯一的持久化面。

CREATE TABLE IF NOT EXISTS detrack_kept_params (
    param TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
