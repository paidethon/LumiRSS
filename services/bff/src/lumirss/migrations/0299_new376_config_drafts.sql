-- 0299: NEW-376 实例配置草案审查 —— 非敏感配置变更先成草案（校验 +
-- 差异 + 生效条件），有权管理员确认后才应用。可草案的键是模块内
-- allow-list（当前唯一真实可写实例键：allow_public_registration）；
-- 应用走 InstanceSettingsStore.set + 审计，绝无敏感凭据路径。

CREATE TABLE IF NOT EXISTS admin_config_drafts (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    draft_value TEXT NOT NULL,
    current_value TEXT NOT NULL,
    validation TEXT NOT NULL,
    effective_notes TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'applied', 'discarded')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_by TEXT,
    applied_at TEXT,
    settled_at TEXT
);
