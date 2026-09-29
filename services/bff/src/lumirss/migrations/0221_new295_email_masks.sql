-- 0221: NEW-295 邮件隐私内容遮罩 —— 用户把邮件中的地址、签名或某段
-- 文字标记为「分享时隐藏」，原文仍私有保存。
--
-- email_masks：一行 = 一条遮罩（kind + 字面文本 value）。遮罩只在
-- share-view / 导出脱敏路径生效；email_materials 原文从不改写。

CREATE TABLE IF NOT EXISTS email_masks (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_masks_material
    ON email_masks(material_id);
