-- 0143 (NEW-213): 标签互斥组 —— 用户定义的一组标签在某条内容上至多选一个。
-- 成员按 tag_id 引用（改名自动跟随，不需要改写）。组删除/标签删除经
-- FK 级联清理成员行。per-user 库 = 只可能是本人的标签与分组。

CREATE TABLE IF NOT EXISTS new213_tag_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS new213_tag_group_members (
    group_id INTEGER NOT NULL REFERENCES new213_tag_groups(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    UNIQUE (group_id, tag_id)
);
