-- 0222: NEW-296 邮件附件单独入库 —— 从已导入邮件挑选附件转成独立资料
-- 条目，保留与原邮件的关系。
--
-- email_attachment_items：一行 = 一个独立附件条目（字节引用 0217 的
-- email_attachment_blobs；parent_* 字段保留与原邮件的关系）。转出的
-- 附件与原邮件互不删除——「单独入库」是复制引用，不是移动。

CREATE TABLE IF NOT EXISTS email_attachment_items (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL,
    ord INTEGER NOT NULL,
    filename TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    parent_subject TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_attachment_items_material
    ON email_attachment_items(material_id);
