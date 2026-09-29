-- 0144: NEW-234 个人批注层 —— 同一文章的批注按用途分层。
--
-- annotation_layers：层定义（名称即用途标签）。层是纯个人结构
-- （per-user 库），默认绝不进入任何共享面。
-- annotations.layer_id：NULL = 未分层（默认层）。删除层时成员批注
-- 回到未分层（layer_id 置 NULL），批注本体永不随层删除。

CREATE TABLE IF NOT EXISTS annotation_layers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE annotations ADD COLUMN layer_id TEXT;

CREATE INDEX IF NOT EXISTS idx_annotations_layer
    ON annotations (layer_id);
