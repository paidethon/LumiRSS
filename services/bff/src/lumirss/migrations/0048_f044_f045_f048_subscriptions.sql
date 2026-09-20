-- 0048: F044 地址迁移标记 + F045 服务端屏蔽规则 + F048 正文提取缓存。
--
-- source_migrations（F044）——旧订阅迁移标记：FreshRSS 无"原位改 URL"
-- 能力，迁移 = 新建订阅 + Lumi 元数据随迁；旧行保留（用户自行退订），
-- replaced_by 关系在这里记录（不删除任何 FreshRSS 数据）。
--
-- feed_filter_rules（F045）——服务端屏蔽规则（每来源 ≤20 条，应用层
-- 限额）：entries 列表编译进 SQL 谓词（OR 连接），分页与计数天然一致；
-- 只影响 Lumi 时间线视图，绝不触碰 FreshRSS 已读/收藏。
--
-- entry_extract_cache（F048）——per-source web 提取正文缓存（≤2MB 有界
-- 上游抓取的产物，可重建；entry_ref 主键，一篇文章至多一份缓存）。

CREATE TABLE IF NOT EXISTS source_migrations (
    old_feed_url TEXT PRIMARY KEY,
    old_subscription_ref TEXT,
    new_feed_url TEXT NOT NULL,
    new_subscription_ref TEXT,
    migrated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS feed_filter_rules (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    field TEXT NOT NULL CHECK (field IN ('title', 'author')),
    op TEXT NOT NULL CHECK (op IN ('contains', 'equals')),
    value TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_feed_filter_rules_feed
    ON feed_filter_rules (feed_url, enabled);

CREATE TABLE IF NOT EXISTS entry_extract_cache (
    entry_ref TEXT PRIMARY KEY,
    content_html TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- F048：per-source 正文提取策略（'rss' 默认 | 'web' 抓原文正文）。
ALTER TABLE source_overrides ADD COLUMN extract_policy TEXT NOT NULL DEFAULT 'rss';

-- F055：per-source 阅读样式覆盖（fontSize/lineHeight/width 子集 JSON）。
ALTER TABLE source_overrides ADD COLUMN reader_style_json TEXT;
