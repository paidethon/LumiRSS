-- 0116: N193 单用户后台任务暂停 — 配额/标志行补位。
--
-- background_paused：1 = 该成员的重型后台工作（订阅投影同步、日报
-- 调度、IMAP 轮询、RAG 增量索引、GPT 日报）被管理员单独立暂停；
-- 登录与阅读完全不受影响（与 users.status 的整账户暂停互不影响）。
-- background_pause_reason：管理员给出的人读原因（≤200 字符），随
-- audit_log 一起落账；恢复时清空。
--
-- active_user_ids() 以 LEFT JOIN 读取本列：没有策略行的成员视为
-- 未暂停（COALESCE 0），后台循环照常覆盖。

ALTER TABLE user_quotas ADD COLUMN background_paused INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_quotas ADD COLUMN background_pause_reason TEXT;
