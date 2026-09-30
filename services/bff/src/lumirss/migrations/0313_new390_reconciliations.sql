-- 0313: NEW-390 迁移结果逐项对账。
--
-- 对照原清单逐条给出 added（新增）/ matched（对应既有）/ failed
-- （该条失败及原因）/ missing（在原清单但任何卷都没出现）。用户逐条
-- 确认（confirmed_json），pending 减到 0 即对账完成——不提供一键全收。

CREATE TABLE IF NOT EXISTS new390_reconciliations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT '',
    expected_json TEXT NOT NULL DEFAULT '[]',
    results_json TEXT NOT NULL DEFAULT '[]',
    confirmed_json TEXT NOT NULL DEFAULT '[]',
    pending_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
