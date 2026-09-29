-- 0242: NEW-316 书签意图字段 —— 收藏时记录「为什么保存」与「希望什么
-- 时候用」，之后可按意图筛选与处理。
--
-- 与书签行 1:1（bookmark_item_uuid 主键，引用 library_bookmarks）；
-- reason/when_to_use 都是用户显式输入的自由文本（长度受限）；没有行
-- = 未表达意图（列表里如实显示为空，不发明默认值）。per-user。

CREATE TABLE IF NOT EXISTS bookmark_intents (
    bookmark_item_uuid TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    when_to_use TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bookmark_intents_when
    ON bookmark_intents (when_to_use);
