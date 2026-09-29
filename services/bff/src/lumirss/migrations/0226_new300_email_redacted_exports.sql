-- 0226: NEW-300 邮件资料脱敏导出 —— 导出前选择是否保留地址和完整邮件
-- 头，生成清楚的字段删除说明。
--
-- email_export_logs：一次导出 = 一行审计：当时的选择（options_json）与
-- 实际删除了哪些字段（removed_json）——脱敏是显式用户选择，默认脱敏，
-- 原文仍私有保存（导出不改库内数据）。

CREATE TABLE IF NOT EXISTS email_export_logs (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL,
    include_addresses INTEGER NOT NULL,
    include_full_headers INTEGER NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    removed_json TEXT NOT NULL DEFAULT '[]',
    exported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_export_logs_material
    ON email_export_logs(material_id);
