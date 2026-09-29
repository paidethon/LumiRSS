-- 0172: NEW-246 资料来源链 —— 手工登记的引用边。
--
-- citation_edges：用户手动登记「A 引用了 B」的一条边。系统绝不推断：
-- 链条查询只走显式登记的边；被引目标没有登记自己的出处（没有出边、
-- 也没有 NEW-245 的引文登记）时，如实标注「中间环节缺失」，不猜测。
-- 同一对 (from_ref, to_ref) 至多一条（应用层查重 → 409）。

CREATE TABLE IF NOT EXISTS citation_edges (
    id TEXT PRIMARY KEY,
    from_ref TEXT NOT NULL,
    to_ref TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_citation_edges_from ON citation_edges (from_ref);
CREATE INDEX IF NOT EXISTS idx_citation_edges_to ON citation_edges (to_ref);
