-- 0237: NEW-311 浏览器书签目录导入 —— 解析本人导出的 Netscape HTML，
-- 预览目录映射与重复链接，确认后形成可追溯的导入集合。
--
-- 集合行是「这次导入发生了什么」的台账：total/imported/skipped 是真实
-- 计数，folders_json 记录用户选择的目录范围；逐条 item 行带最终状态
-- （imported / duplicate / invalid / excluded），诚实可查、绝不静默。
-- 书签本体仍走 library_bookmarks 唯一索引（重复 URL 收敛），本表不
-- 复制书签数据。per-user（RoutingDatabase 按请求身份路由）。

CREATE TABLE IF NOT EXISTS bookmark_import_sets (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL,
    imported INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    folders_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmark_import_set_items (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL REFERENCES bookmark_import_sets(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    folder_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (
        status IN ('imported', 'duplicate', 'invalid', 'excluded')
    ),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_import_set_items
    ON bookmark_import_set_items (set_id, created_at ASC);
