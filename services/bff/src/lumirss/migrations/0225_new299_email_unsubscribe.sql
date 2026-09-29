-- 0225: NEW-299 通讯退订信息卡 —— 从原文明确提供的 List-Unsubscribe 等
-- 头部展示退订方式，用户主动打开，绝不自动执行退订请求。
--
-- email_unsub_opens：用户「主动打开某条退订途径」的审计记录（只记录
-- 用户点开这一动作；打开本身由用户在邮件客户端/浏览器自行完成，
-- LumiRSS 不发任何请求）。

CREATE TABLE IF NOT EXISTS email_unsub_opens (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL,
    method TEXT NOT NULL,
    target TEXT NOT NULL,
    opened_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_unsub_opens_material
    ON email_unsub_opens(material_id);
