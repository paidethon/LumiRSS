-- 0251: NEW-328 库同步冲突收件箱 —— 个人修正 vs 源文件更新并排展示。
--
-- obsidian_note_corrections：用户对某条笔记的个人修正层（标题/笔记
-- 文本），base_content_hash 记录修正所基于的源内容版本——Lumi 侧
-- 独立层，绝不回写 Vault。
--
-- obsidian_sync_conflicts：源内容 hash 变化且个人修正未重定时产生的
-- 冲突行，side-by-side 数据（源版本 vs 个人修正）在检测时快照；解决
-- 只能是显式二选一：keep_independent（修正重定基到新版本，独立层
-- 保留）或 adopt_source（放弃个人修正层，采用源版本）。

CREATE TABLE IF NOT EXISTS obsidian_note_corrections (
    note_uuid TEXT PRIMARY KEY,
    base_content_hash TEXT NOT NULL,
    personal_title TEXT NOT NULL DEFAULT '',
    personal_note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obsidian_sync_conflicts (
    id TEXT PRIMARY KEY,
    note_uuid TEXT NOT NULL,
    base_content_hash TEXT NOT NULL,
    current_content_hash TEXT NOT NULL,
    source_title TEXT NOT NULL DEFAULT '',
    source_excerpt TEXT NOT NULL DEFAULT '',
    personal_title TEXT NOT NULL DEFAULT '',
    personal_note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (
        status IN ('open', 'kept_independent', 'adopted_source')
    ),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_obsidian_sync_conflicts_status
    ON obsidian_sync_conflicts (status, created_at DESC);
