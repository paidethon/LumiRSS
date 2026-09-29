-- 0145: NEW-235 笔记模板填空 —— 阅读记录字段模板 + 笔记上的结构化填充。
--
-- note_field_templates：模板定义（name + 有序字段 [{key,label}]）。
-- lumi_notes.template_fill_json：{"templateId":...,"values":{key:value}}。
-- content_md 仍是笔记正文单一真源——模板填充是附加结构（与 N079
-- sections_json 同一先例），自由文本区永不被迫改写。

CREATE TABLE IF NOT EXISTS note_field_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE lumi_notes ADD COLUMN template_fill_json TEXT;
