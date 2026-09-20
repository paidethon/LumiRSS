-- 0063: W6 日报域（F101 近期材料去重 / F102 手工候选素材池）。
-- F101：lookback_days = 回看窗口天数（0=关，默认 7，上限 90）；
--       选材时排除窗口内已发布期号引用过的材料（草稿不算已用）。
ALTER TABLE gpt_digest_configs ADD COLUMN lookback_days INTEGER NOT NULL DEFAULT 7;

-- F102：手工候选素材池。一份配置一个池；entry_ref 为读者条目引用；
-- used_issue_key 非空 = 已被某期消费（移出待用）；UNIQUE 防重复添加。
CREATE TABLE digest_material_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL,
    entry_ref TEXT NOT NULL,
    added_at TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    used_issue_key TEXT,
    UNIQUE(config_id, entry_ref)
);

CREATE INDEX digest_material_pool_config ON digest_material_pool (config_id, position);
