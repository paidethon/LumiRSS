-- 0324: R07 服务端受限写入导出 —— 每用户导出偏好 + 导出台账。
--
-- 与 ADR-0004 只读投影的关系：读面（obsidian.py）对 /vault 绝不写；
-- 写面（obsidian_export.py）只落部署上独立挂载的「导出根」
-- （容器内路径由 LUMIRSS_OBSIDIAN_EXPORT_DIR 给出，生产 overlay 挂
-- /vault-export，rw），且只创建 <root>/<subdir>/<user_id>/ 下的新文件，
-- 绝不覆盖已存在文件（用户手写保护）。
--
-- 导出子目录是用户级偏好（单行 id=1，与 obsidian_export_settings 的
-- 模板行同一惯例）：默认 LumiRSS；合法值在应用层校验（拒绝 ..、绝对
-- 路径、反斜杠；见 obsidian_export.validate_export_subdir）。
--
-- 台账（obsidian_export_log）记录每次 written / exists 结果：status
-- 端点的「今日用量、最近导出」与每日写入容量上限都从这张表推导，
-- 不另设计数器。文件本体永远以文件系统为准——台账是审计投影，
-- 用户删掉导出的 .md 不产生任何清理动作。

CREATE TABLE IF NOT EXISTS obsidian_export_prefs (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    export_subdir TEXT NOT NULL DEFAULT 'LumiRSS',
    updated_at TEXT
);

INSERT INTO obsidian_export_prefs (id, export_subdir) VALUES (1, 'LumiRSS');

CREATE TABLE IF NOT EXISTS obsidian_export_log (
    id TEXT PRIMARY KEY,
    ref TEXT NOT NULL,
    content_id TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('written', 'exists')),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obsidian_export_log_created
    ON obsidian_export_log(created_at);
