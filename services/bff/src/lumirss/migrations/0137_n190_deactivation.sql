-- 0135: N190 账户停用前迁出 —— 用户发起的停用请求。
--
-- users.status 的 CHECK 约束只有 ('active','paused')，SQLite 不能改
-- CHECK——这里追加独立的请求时间戳列：pending_deletion ≡
-- status='paused' AND deactivation_requested_at IS NOT NULL。
-- 宽限期（默认 14 天）内运营者用既有 resume 端点恢复 = 清本列 +
-- status 复位 active。没有自动删除作业：到期后的物理删除由运营者
-- 手动执行（界面如实说明）。请求时间戳为 epoch 秒（users 表惯例）。

ALTER TABLE users ADD COLUMN deactivation_requested_at INTEGER;
