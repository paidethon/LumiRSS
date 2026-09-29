-- 0245: NEW-322 链接解析报告 —— 用户逐项纠正 Wiki 链接的导入映射。
--
-- 报告本身是纯读计算（明确 / 歧义 / 失效），不落库；本表只存用户对
-- 单条链接的显式纠正（(note_uuid, raw) → 指定目标笔记），报告重算时
-- 作为该条链接的覆盖裁决。绝不写 Vault。

CREATE TABLE IF NOT EXISTS obsidian_link_corrections (
    note_uuid TEXT NOT NULL,
    raw TEXT NOT NULL,
    target_uuid TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (note_uuid, raw)
);

CREATE INDEX IF NOT EXISTS idx_obsidian_link_corrections_target
    ON obsidian_link_corrections (target_uuid);
