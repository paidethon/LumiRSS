-- 0217: NEW-291 用户 EML 导入 —— 用户上传自己的邮件文件为资料条目。
--
-- email_materials：一条 = 用户导入的一封邮件（解析自 EML；per-user 库，
-- 账户完全隔离）。body_html 只存 mail_sanitize 净化后的版本（原始 HTML
-- 不入库）；body_digest 是 body_text 的 sha256（NEW-298 重复识别用）。
-- email_attachment_blobs：导入时解析出的附件（大小封顶内真实存字节，
-- 超限只存元数据并如实标 stored=0，NEW-296 转独立条目时取用）。

CREATE TABLE IF NOT EXISTS email_materials (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    from_name TEXT NOT NULL DEFAULT '',
    from_addr TEXT NOT NULL DEFAULT '',
    to_addrs TEXT NOT NULL DEFAULT '',
    date_hdr TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    body_html TEXT NOT NULL DEFAULT '',
    headers_json TEXT NOT NULL DEFAULT '{}',
    attachments_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    body_digest TEXT NOT NULL DEFAULT '',
    raw_bytes INTEGER NOT NULL DEFAULT 0,
    source_label TEXT NOT NULL DEFAULT '',
    import_kind TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_materials_message_id
    ON email_materials(message_id);
CREATE INDEX IF NOT EXISTS idx_email_materials_from_addr
    ON email_materials(from_addr);
CREATE INDEX IF NOT EXISTS idx_email_materials_source
    ON email_materials(source_label);

CREATE TABLE IF NOT EXISTS email_attachment_blobs (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL,
    ord INTEGER NOT NULL,
    filename TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    stored INTEGER NOT NULL DEFAULT 0,
    data BLOB,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_attachment_blobs_material
    ON email_attachment_blobs(material_id);
