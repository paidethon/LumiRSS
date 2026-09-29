-- 0249: NEW-326 附件引用可移植打包 —— 选中笔记 + 允许包含的附件 →
-- 相对链接目录（zip），包内引用经越界校验。
--
-- 台账行存打包清单与校验结论（附件收录 / 越界与缺失等违规逐条列出）；
-- zip 本体即时组装返回（或按台账从当前 Vault 重装），不在库里囤二进制。

CREATE TABLE IF NOT EXISTS obsidian_portable_bundles (
    id TEXT PRIMARY KEY,
    notes_json TEXT NOT NULL DEFAULT '[]',
    attachments_json TEXT NOT NULL DEFAULT '[]',
    violations_json TEXT NOT NULL DEFAULT '[]',
    note_count INTEGER NOT NULL DEFAULT 0,
    attachment_count INTEGER NOT NULL DEFAULT 0,
    violation_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
