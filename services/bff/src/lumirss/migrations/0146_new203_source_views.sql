-- 0146: NEW-203 来源分流视图 —— 同一 feed 的多个个人视图（读取侧）。
--
-- 视图 = (feed_url, 名称, 匹配字段, 包含关键词)。**读取侧派生**：
-- 不新建抓取任务、不复制条目、不改原始文章身份——唯一消费点是
-- search_entries 投影的过滤查询（视图行被删除/上游退订后如实为空）。
-- 同一 (feed_url, name) 唯一（视图名是用户的稳定锚点）。

CREATE TABLE IF NOT EXISTS new203_source_views (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    name TEXT NOT NULL,
    field TEXT NOT NULL CHECK (field IN ('title', 'content', 'author')),
    value TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_new203_view_name
    ON new203_source_views (feed_url, name);

CREATE INDEX IF NOT EXISTS ix_new203_views_feed
    ON new203_source_views (feed_url, created_at);
