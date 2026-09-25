-- 0115: N191 用户额度策略包 — 每账户策略行（控制库真源）。
--
-- user_quotas：user_id 主键的一行式策略包。caps 是 JSON 对象
-- {"maxSources": <int>, "aiQuotaPerDay": <int>}，键可缺省——缺省即
-- 「管理员未设限」，绝不编造默认上限。updated_by/updated_at 记录最后
-- 一次管理操作（审计明细落 audit_log，本表不存历史）。
--
-- 与 0089 同理：本表在每用户库也会创建但恒空——单序列迁移的现实，
-- 只有控制库写入行。成员自助提升在服务端拦截：订阅计数与 AI 配额
-- 咨询都在 BFF 内读本表，成员没有任何写路径。
--
-- N193 在 0116 为同一行补 background_paused/background_pause_reason
-- 列（「配额/标志行」共位，避免第二张每用户控制表）。

CREATE TABLE IF NOT EXISTS user_quotas (
    user_id TEXT PRIMARY KEY,
    caps TEXT NOT NULL DEFAULT '{}',
    updated_by TEXT,
    updated_at INTEGER NOT NULL DEFAULT 0
);
