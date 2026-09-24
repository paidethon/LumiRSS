-- 0102 (N125): 邮件附件的有界存储。
-- 附件在 ingest 时提取：仅放行 pdf / 图片 / 文本 / office 文档；
-- 脚本与可执行类型（.exe/.sh/.js/.html 等，按扩展名+MIME 双重判定）
-- 与超限文件（单文件 >5MB、每封 >20 个）不入库，只在元数据里如实
-- 列为「已跳过」。内容以 BLOB 有界存储，下载走附件语义响应头。
CREATE TABLE mail_attachments (
    id TEXT PRIMARY KEY,
    list_uuid TEXT NOT NULL,
    message_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    content BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_mail_attachments_message ON mail_attachments(list_uuid, message_id);
