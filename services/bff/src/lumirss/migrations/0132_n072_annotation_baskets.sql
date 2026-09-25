-- 0132: N072 批注精选篮 —— 跨篇手工挑选的批注集合（导出/回跳单元）。
--
-- annotation_baskets：篮本身（名字 + 创建时间）；per-user 库中只可能
-- 是本人的篮，无需 user 列。annotation_basket_items：成员关系
-- （复合主键 = 同一篮内同一批注至多一条；加入是幂等的）。批注本体
-- 仍在 annotations 表（单一真源）——篮只存引用，不 shadow-copy；
-- 批注被删除后成员行如实保留并在读取侧标 broken（stale 口径一致）。

CREATE TABLE IF NOT EXISTS annotation_baskets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotation_basket_items (
    basket_id TEXT NOT NULL,
    annotation_id TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (basket_id, annotation_id)
);

CREATE INDEX IF NOT EXISTS idx_annotation_basket_items_basket
    ON annotation_basket_items (basket_id, added_at);
