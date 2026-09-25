-- 0109: N140 双向交接记录（导出到 Obsidian / 打开 / 显式导入确认）。
--
-- 每次 export / open 交接都落一条 pending；只有用户在 Obsidian 完成保存
-- 后【显式】确认（POST /obsidian/handoff/{id}/confirm）才置 confirmed ——
-- 页面可见性 / 重新加载等被动事件绝不自动确认（诚实交接，ADR 0004：
-- Lumi 不写 Vault，保存只发生在用户于 Obsidian 中确认时）。
CREATE TABLE obsidian_handoff_log (
    id TEXT PRIMARY KEY,
    direction TEXT NOT NULL CHECK (direction IN ('export', 'open', 'import_confirm')),
    entry_ref TEXT NOT NULL DEFAULT '',
    note_name TEXT NOT NULL DEFAULT '',
    policy TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed')),
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE INDEX ix_obsidian_handoff_log_created ON obsidian_handoff_log(created_at);
