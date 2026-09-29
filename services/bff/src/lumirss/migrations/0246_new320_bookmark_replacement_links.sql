-- 0246: NEW-320 书签失效替代关联 —— 原链接失效后用户指定可信的新来源，
-- 保留旧链接与替换理由，引用者能看到变更。
--
-- 一行 = 一次替代关联（旧书签 → 新 URL + 理由）：旧书签绝不删除/改写
-- （保留旧链接是硬要求）；同一旧书签可多次替代（历史保留，最后一次
-- 为当前生效）。引用者视角 = 按旧 ref 查询能拿到完整变更记录
-- （旧 URL、新 URL、理由、时间）。per-user。

CREATE TABLE IF NOT EXISTS bookmark_replacement_links (
    id TEXT PRIMARY KEY,
    bookmark_item_uuid TEXT NOT NULL,
    new_url TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_replacement_links_bookmark
    ON bookmark_replacement_links (bookmark_item_uuid, created_at DESC);
