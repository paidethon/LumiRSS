-- 0171: NEW-245 引文出处补全 —— 引文登记 + 用户补充字段。
--
-- citation_records：用户登记的个人引用（原始值：登记时填写的
-- author/date，可以是 NULL = 原始就缺失）。原始值一旦登记不改写
-- （重新登记同一 ref → 409，保原始值不被覆盖）。
--
-- citation_field_supplements：用户补充的 author/date（origin 天然是
-- 「用户补充」——表里只有补充值，原始值永远在 citation_records），
-- 每字段至多一条（UNIQUE），可删除（撤销补充恢复缺失态）。

CREATE TABLE IF NOT EXISTS citation_records (
    citation_ref TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    date_value TEXT,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citation_field_supplements (
    id TEXT PRIMARY KEY,
    citation_ref TEXT NOT NULL,
    field TEXT NOT NULL CHECK (field IN ('author', 'date')),
    value TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (citation_ref, field)
);
