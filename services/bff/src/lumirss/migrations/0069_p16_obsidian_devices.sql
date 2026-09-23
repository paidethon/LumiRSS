-- 0069: P16 Obsidian 多设备交接基础 —— 设备档案 + 导出模板（每用户库）。
--
-- 设备档案只服务于 obsidian:// URI 生成（用户自己设备上的 Obsidian），
-- 与服务器端 vault_path（env 只读挂载模式的容器内路径）完全无关：
-- vault_path 供扫描/投影使用，设备档案只在生成深链时描述用户本机的
-- Obsidian vault 名称。Vault 依旧只读 —— Lumi 永不写 Vault（ADR 0004）；
-- 真正的写入由用户在 Obsidian 里确认保存时发生。
--
-- 导出模板单独一行（id=1）；空模板 = 使用代码内 DEFAULT_TEMPLATE
-- （单一事实源在 obsidian_template.py，避免 SQL 字面量与代码漂移）。
CREATE TABLE IF NOT EXISTS obsidian_device_profiles (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    vault_name TEXT NOT NULL,
    vault_identifier TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT 'other',
    created_at TEXT NOT NULL
);

CREATE INDEX ix_obsidian_device_created ON obsidian_device_profiles(created_at);

CREATE TABLE IF NOT EXISTS obsidian_export_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    template TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);

INSERT INTO obsidian_export_settings (id, template) VALUES (1, '');
