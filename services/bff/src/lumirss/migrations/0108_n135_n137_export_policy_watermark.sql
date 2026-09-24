-- 0108: N135 导出重名策略 + N137 批注导出水位（增量批注导出）。
--
-- N135：obsidian://new URI 无法探测目标库内是否已存在同名笔记（官方
-- URI 限制），因此提供显式命名策略而非假装能查重：
-- - timestamp_suffix（默认）：文件名追加 -YYYYMMDD-HHmm，已知已导出过
--   的文章再导出时不覆盖旧笔记；
-- - exact：完全按标题命名（用户明确要求同名覆盖语义时自担风险）。
-- 校验在应用层（obsidian_devices.ObsidianExportSettingsStore），SQLite
-- 的 ADD COLUMN 不便携带 CHECK，保持迁移最小。
ALTER TABLE obsidian_export_settings ADD COLUMN export_name_policy TEXT NOT NULL DEFAULT 'timestamp_suffix';

-- N137：批注导出水位的追加日志。水位 = MAX(exported_at)；增量导出 =
-- annotations.updated_at > 水位。重复 mark 只是追加日志行（幂等：
-- 水位只前进，增量查询按时间比较，不会重复计数）。
CREATE TABLE annotation_export_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exported_at TEXT NOT NULL,
    entry_refs_json TEXT NOT NULL DEFAULT '[]',
    count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX ix_annotation_export_log_time ON annotation_export_log(exported_at);
