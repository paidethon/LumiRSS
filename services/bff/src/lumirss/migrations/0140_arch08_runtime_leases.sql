-- 0140: ARCH-08 运行时窗口租约 —— 调度器跨进程互斥。
--
-- runtime_leases：digest / gpt-digest 等周期任务在真正产生副作用
-- （SMTP 发送 / AI 生成）之前，按「精确窗口」取租约（scope 主键）。
-- 存活租约不可抢占（expires_at 未到），过期租约可被接管（崩溃恢复），
-- release 按 owner 校验（绝不释放他人窗口）。每次 acquire 顺带清扫
-- 已过期行，表规模有界（每个窗口一行，过期即清）。
--
-- 无 Redis / 无外部依赖：互斥语义完全落在该用户的 lumi.sqlite 里，
-- 与单二进制 SQLite 架构一致（ARCH-08 验收是行为可测试，不是重写）。

CREATE TABLE IF NOT EXISTS runtime_leases (
  scope TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  acquired_at TEXT NOT NULL
);
