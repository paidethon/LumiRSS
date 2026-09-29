-- 0212: NEW-286 简报栏目配方 —— 栏目顺序、字数预算与选择规则的可复用
-- 配方。sections_json = [{key,label,rule,budget,feedUrl?}]，rule ∈
-- starred(已标星) / recent(最新预算条数) / feed(指定来源)。生成器按
-- 配方决定每栏目取什么、取多少；下一期可原样复用或建稿后微调。

CREATE TABLE IF NOT EXISTS briefing_recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sections_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
