-- 0223: NEW-297 邮件导入规则预览 —— 写入前用样本检查主题清理、标签和
-- 来源映射规则，确认后应用于本批。
--
-- email_import_rules：一行 = 一条已保存的导入规则（kind + config_json）。
-- 预览是纯计算（零写入）；「应用于本批」只影响当次导入调用传入的文件。

CREATE TABLE IF NOT EXISTS email_import_rules (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
