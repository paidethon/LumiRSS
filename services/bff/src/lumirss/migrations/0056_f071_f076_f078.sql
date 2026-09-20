-- 0056: F071 duplicate_pairs + F076 graph_views + F078 search_synonyms
-- （三表分立，合一个迁移文件）。

-- F071 疑似重复审核：scan 产出 pending 对；confirm 创建
-- item_relations kind='duplicate' 关联；whitelisted 永不重现
-- （UNIQUE(a_ref,b_ref)：已存在的对扫描时不动）。从不自动删除条目。
CREATE TABLE duplicate_pairs (
    id TEXT PRIMARY KEY,
    a_ref TEXT NOT NULL,
    b_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'confirmed', 'ignored', 'whitelisted'
    )),
    created_at TEXT NOT NULL,
    UNIQUE (a_ref, b_ref)
);
CREATE INDEX idx_duplicate_pairs_status ON duplicate_pairs (status, created_at DESC);

-- F071 配套：手工关联增加 kind（旧数据 = 'manual'；确认重复写
-- 'duplicate'）。
ALTER TABLE item_relations ADD COLUMN kind TEXT NOT NULL DEFAULT 'manual';

-- F076 图谱命名视图：布局（≤200 节点位置）+ filters + focus 节点。
CREATE TABLE graph_views (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    layout_json TEXT NOT NULL,
    filters_json TEXT NOT NULL,
    focus_node TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (name)
);

-- F078 检索同义词：term 命中时 OR 并入 expansions（单层，不递归）。
CREATE TABLE search_synonyms (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL UNIQUE,
    expansions TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
