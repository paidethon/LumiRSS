-- 0103 (N126/N127): 邮件正文显示模式 + 来源身份提示。
-- N126：被阻止的外链媒体清单（mail_sanitize 本就剥离全部远程图片，
-- 这里在 ingest 时把被剥掉的 URL 如实记录，有界 ≤20 条）。
ALTER TABLE mail_bridge_entries ADD COLUMN blocked_media_json TEXT;

-- N127：服务端在 ingest 时计算的来源身份提示（From vs Reply-To 不一致
-- / 显示名中的域名与实际邮箱域不一致）；只作中性提示，不做任何
-- 反欺骗断言（SPF/DKIM 客户端不验证）。
ALTER TABLE mail_bridge_entries ADD COLUMN identity_hints_json TEXT;
