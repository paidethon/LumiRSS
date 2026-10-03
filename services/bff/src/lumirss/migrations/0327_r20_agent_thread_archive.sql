-- R20：会话归档。NULL = 未归档（默认工作集）；非 NULL = 归档时间。
-- 归档是软状态：会话与消息原样保留，列表默认视图收起、可恢复。
ALTER TABLE agent_threads ADD COLUMN archived_at TEXT;
